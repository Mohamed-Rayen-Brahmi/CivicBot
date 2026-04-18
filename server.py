import os
import sys
import threading

# --- DLL Search Path Fix for CUDA on Windows ---
if sys.platform == 'win32':
    # Aggressively prioritize Torch's bundled DLL paths to avoid loading broken system-wide CUDNN
    torch_lib = os.path.join(os.getcwd(), ".venv", "Lib", "site-packages", "torch", "lib")
    if os.path.exists(torch_lib):
        # We add the torch lib to search path
        os.add_dll_directory(torch_lib)
        # We also clear system-wide NVIDIA/CUDA paths from the process's PATH to avoid confusion
        current_path = os.environ.get("PATH", "").split(os.pathsep)
        new_path = [torch_lib]
        for p in current_path:
            if "NVIDIA" not in p and "CUDA" not in p:
                new_path.append(p)
        os.environ["PATH"] = os.pathsep.join(new_path)

# --- Network Timeout Resiliency ---
os.environ["HF_HUB_READ_TIMEOUT"] = "120"
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "120"
os.environ["PIP_DEFAULT_TIMEOUT"] = "1000"

import asyncio
import websockets
import json
import logging
import io
import time
import requests
import numpy as np
import scipy.signal
from typing import Any
import cv_module
# Faster-Whisper and Kokoro imports
from faster_whisper import WhisperModel
from kokoro import KPipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AIPipeline")

# --- Configuration ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "tinyllama")
MODEL_FALLBACK = os.getenv("MODEL_FALLBACK", "tinyllama:latest")
WS_PORT = int(os.getenv("WS_PORT", "8765"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "80"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "auto")
WHISPER_VAD_FILTER = os.getenv("WHISPER_VAD_FILTER", "true").strip().lower() in {"1", "true", "yes", "on"}
KOKORO_DEVICE = os.getenv("KOKORO_DEVICE", "cpu")
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_bella")
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.1"))
TURN_SILENCE_SECONDS = float(os.getenv("TURN_SILENCE_SECONDS", "0.45"))
TTS_CHUNK_MAX_CHARS = int(os.getenv("TTS_CHUNK_MAX_CHARS", "70"))
LOCATION_ACCEPT_NON_ANDROID = os.getenv("LOCATION_ACCEPT_NON_ANDROID", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
AUDIO_ENERGY_THRESHOLD = float(os.getenv("AUDIO_ENERGY_THRESHOLD", "0.0004"))
STT_CHUNK_BYTES = int(os.getenv("STT_CHUNK_BYTES", "32000"))
PRELOAD_AUDIO_MODELS = os.getenv("PRELOAD_AUDIO_MODELS", "true").strip().lower() in {"1", "true", "yes", "on"}
OLLAMA_REQUEST_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", "60"))

SYSTEM_PROMPT = (
    "You are CivicBot, a concise road-assistant robot. "
    "Respond in plain language, max 2 short sentences. "
    "Prioritize: 1) safety, 2) clarity, 3) actionable next step. "
    "If user audio is unclear, politely ask a short clarification question. "
    "Avoid technical jargon and avoid meta comments. "
    "Local context: ISET Bizerte and surrounding Bizerte areas in Tunisia."
)

MAX_HISTORY_TURNS = 5
conversation_history = []
connected_clients = set()
connected_clients_lock = threading.Lock()

_whisper_model = None
_kokoro_pipeline = None
_whisper_lock = threading.Lock()
_kokoro_lock = threading.Lock()

# --- State ---
class PipelineState:
    def __init__(self):
        self.audio_buffer = bytearray()
        self.turn_buffer = ""
        self.last_voice_timestamp = 0.0
        self.flush_task = None
        self.stt_busy = False
        
state = PipelineState()


def _is_preferred_location_source(source: str) -> bool:
    src = (source or "").strip().lower()
    if LOCATION_ACCEPT_NON_ANDROID:
        return True
    return ("android" in src) or (src in {"mobile", "phone"})


def _preload_audio_models_sync() -> None:
    try:
        get_whisper_model()
        get_kokoro_pipeline()
        logger.info("Audio models preloaded in background.")
    except Exception as preload_exc:
        logger.warning("Audio model preload skipped due to error: %s", preload_exc)


async def _preload_audio_models_async() -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _preload_audio_models_sync)

def get_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model


def _get_llm_candidates() -> list[str]:
    candidates = []
    for name in [MODEL_NAME, MODEL_FALLBACK]:
        clean = (name or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)
    return candidates

    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model

        # Lazy-load on first transcription request to reduce startup memory.
        try:
            _whisper_model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
            logger.info("Faster-Whisper loaded on %s (%s).", WHISPER_DEVICE, WHISPER_COMPUTE_TYPE)
        except Exception as whisper_exc:
            logger.warning(
                "Whisper init failed on %s: %s. Falling back to CPU int8.",
                WHISPER_DEVICE,
                whisper_exc,
            )
            _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            logger.info("Faster-Whisper loaded on CPU (int8 fallback).")

        return _whisper_model


def get_kokoro_pipeline():
    global _kokoro_pipeline
    if _kokoro_pipeline is not None:
        return _kokoro_pipeline

    with _kokoro_lock:
        if _kokoro_pipeline is not None:
            return _kokoro_pipeline

        # Lazy-load on first TTS request to reduce idle RAM usage.
        try:
            _kokoro_pipeline = KPipeline(lang_code='a', device=KOKORO_DEVICE)
            logger.info("Kokoro Pipeline loaded on %s.", KOKORO_DEVICE)
        except Exception as kokoro_exc:
            logger.warning("Kokoro init failed on %s: %s. Falling back to CPU.", KOKORO_DEVICE, kokoro_exc)
            _kokoro_pipeline = KPipeline(lang_code='a', device='cpu')
            logger.info("Kokoro Pipeline loaded on CPU fallback.")

        return _kokoro_pipeline


# --- VAD & STT logic ---
def process_audio_buffer(pcm_data: bytes) -> str:
    if not pcm_data:
        return ""

    whisper_model: Any = get_whisper_model()
    if whisper_model is None:
        return ""
    # Android sends 16bit PCM mono at 16kHz
    audio_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

    if audio_np.size == 0:
        return ""
    
    # Simple check for silence (Energy based VAD placeholder)
    energy = np.sum(audio_np**2) / len(audio_np)
    if energy < AUDIO_ENERGY_THRESHOLD:
        return ""
        
    logger.info("Running STT...")
    transcribe_kwargs = {
        "beam_size": 1,
        "vad_filter": WHISPER_VAD_FILTER,
    }
    if WHISPER_LANGUAGE and WHISPER_LANGUAGE.lower() != "auto":
        transcribe_kwargs["language"] = WHISPER_LANGUAGE

    try:
        segments, _ = whisper_model.transcribe(audio_np, **transcribe_kwargs)
    except Exception as stt_exc:
        logger.warning("STT transcription failed: %s", stt_exc)
        return ""
    
    transcription = ""
    for segment in segments:
        transcription += segment.text + " "
        
    return transcription.strip()


# --- LLM Logic ---
async def call_llm(prompt: str, ws, emotion_callback):
    logger.info(f"LLM Prompt: {prompt}")

    cv_context = cv_module.get_context()
    history_block = "\n".join(
        [
            f"Turn {i + 1} User: {turn['user']}\nTurn {i + 1} Assistant: {turn['assistant']}"
            for i, turn in enumerate(conversation_history[-MAX_HISTORY_TURNS:])
        ]
    )

    composed_user_prompt = (
        f"Conversation history (latest first):\n{history_block if history_block else '(none)'}\n\n"
        f"Camera context: {cv_context}\n\n"
        f"Current user message: {prompt}"
    )
    
    base_payload = {
        "system": SYSTEM_PROMPT,
        "prompt": composed_user_prompt,
        "stream": True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "num_predict": OLLAMA_NUM_PREDICT,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }
    
    # Use loop executor to avoid blocking the websocket while waiting for the slow LLM
    loop = asyncio.get_event_loop()
    last_error = None
    for candidate in _get_llm_candidates():
        payload = dict(base_payload)
        payload["model"] = candidate
        try:
            def fetch_stream():
                return requests.post(
                    OLLAMA_URL,
                    json=payload,
                    stream=True,
                    timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
                )

            response = await loop.run_in_executor(None, fetch_stream)
            response.raise_for_status()

            sentence_buffer = ""
            full_assistant_text = ""
            # The iteration itself should be done carefully
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    word = data.get("response", "")
                    sentence_buffer += word
                    full_assistant_text += word

                    # if we hit a sentence or significant pause boundary, stream to TTS
                    if any(punct in word for punct in ['.', '!', '?', ';', ',']):
                        # Only chunk on comma if we have a bit of text to make it sound natural
                        if ',' in word and len(sentence_buffer) < 40:
                            continue

                        await process_tts_and_send(sentence_buffer.strip(), ws)
                        sentence_buffer = ""
                    elif len(sentence_buffer) >= TTS_CHUNK_MAX_CHARS:
                        await process_tts_and_send(sentence_buffer.strip(), ws)
                        sentence_buffer = ""

            if sentence_buffer:
                await process_tts_and_send(sentence_buffer.strip(), ws)

            conversation_history.append({
                "user": prompt.strip(),
                "assistant": full_assistant_text.strip() or "(no output)"
            })
            if len(conversation_history) > MAX_HISTORY_TURNS:
                del conversation_history[:-MAX_HISTORY_TURNS]

            return
        except Exception as e:
            last_error = e
            logger.warning("LLM model '%s' failed: %s", candidate, e)

    logger.error("Ollama API failed for all configured models: %s", last_error)
    await ws.send(json.dumps({"type": "llm", "text": f"Error thinking: {last_error}", "emotion": "sad"}))

# --- TTS Logic ---
async def process_tts_and_send(text: str, ws):
    if not text:
        return
        
    logger.info(f"Generating TTS for: {text}")
    # Notify UI
    await ws.send(json.dumps({"type": "llm", "text": text, "emotion": "talking"}))
    
    try:
        kokoro_pipeline = get_kokoro_pipeline()
        generator = kokoro_pipeline(text, voice=KOKORO_VOICE, speed=KOKORO_SPEED)
        for i, (gs, ps, audio) in enumerate(generator):
            if audio is None:
                continue
            audio_np = audio # This is usually float32 at 24kHz
            
            # resample 24kHz to 16kHz (polyphase is faster)
            resampled_audio = scipy.signal.resample_poly(audio_np, 16000, 24000)
            
            # convert to 16-bit PCM with volume boost (loud version)
            pcm_audio = (resampled_audio * 1.5 * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
            await ws.send(pcm_audio)
    except Exception as e:
        logger.error(f"TTS Error: {e}")


# --- WS Server ---
async def flush_turn(ws):
    global state
    while True:
        try:
            await asyncio.sleep(0.1)
            if state.turn_buffer and (time.time() - state.last_voice_timestamp > TURN_SILENCE_SECONDS):
                final_transcript = state.turn_buffer.strip()
                state.turn_buffer = ""
                logger.info(f"Turn finalized: {final_transcript}")
                # Removing "Thinking" UI update as requested
                # await ws.send(json.dumps({"type": "llm", "text": f"Heard: {final_transcript}", "emotion": "thinking"}))
                
                # Start LLM response
                asyncio.create_task(call_llm(final_transcript, ws, None))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Flush loop error: {e}")
            break

async def handle_connection(ws):
    logger.info("Client connected")
    with connected_clients_lock:
        connected_clients.add(ws)

    global state
    state.audio_buffer.clear()
    state.turn_buffer = ""
    state.last_voice_timestamp = 0
    
    # Start flush monitor
    flush_task = asyncio.create_task(flush_turn(ws))
    
    try:
         async for message in ws:
             if isinstance(message, bytes):
                 state.audio_buffer.extend(message)
                 
                 # Process chunks (default 1 second of audio: 32000 bytes at 16kHz 16-bit mono).
                 if len(state.audio_buffer) >= STT_CHUNK_BYTES and not state.stt_busy:
                     pcm_to_process = bytes(state.audio_buffer)
                     state.audio_buffer.clear()
                     state.stt_busy = True
                     loop = asyncio.get_event_loop()
                     try:
                         transcription = await loop.run_in_executor(None, process_audio_buffer, pcm_to_process)
                     except Exception as stt_exc:
                         logger.warning("STT chunk processing error: %s", stt_exc)
                         transcription = ""
                     finally:
                         state.stt_busy = False
                     if transcription:
                         logger.info(f"Interim Transcription: {transcription}")
                         await ws.send(json.dumps({"type": "stt", "text": transcription, "emotion": "listening"}))
                         state.turn_buffer += transcription + " "
                         state.last_voice_timestamp = time.time()
                         
             elif isinstance(message, str):
                 logger.info(f"Received text payload: {message}")
                 try:
                     payload = json.loads(message)
                     if payload.get("type") == "location":
                         lat = payload.get("latitude")
                         lon = payload.get("longitude")
                         if lat is not None and lon is not None:
                             source = str(payload.get("source", "client"))
                             if _is_preferred_location_source(source):
                                 cv_module.update_location(lat, lon, source=source)
                                 logger.info("GPS location updated (%s): lat=%s lon=%s", source, lat, lon)
                             else:
                                 logger.info("Ignored non-android GPS source: %s", source)
                     elif payload.get("type") == "cv_config":
                         min_conf = payload.get("minConfidence")
                         updated = cv_module.update_runtime_config(min_confidence=min_conf)
                         logger.info("CV config updated: %s", updated)
                 except Exception:
                     pass
                 
    except websockets.exceptions.ConnectionClosed:
           logger.info("Client disconnected")
    finally:
           flush_task.cancel()
           with connected_clients_lock:
              connected_clients.discard(ws)

async def main():
    cv_module.start()

    async def broadcast_cv_events():
        last_updated = -1
        while True:
            await asyncio.sleep(0.5)
            payload = cv_module.get_context_payload()
            updated_at = int(payload.get("updated_at", 0))
            if updated_at <= 0 or updated_at == last_updated:
                continue

            event = {
                "type": "cv",
                "updatedAt": updated_at,
                "summary": payload.get("summary"),
                "roadDamageCount": payload.get("road_damage_count", 0),
                "roadDamageLabels": payload.get("road_damage_labels", []),
                "lastReportPath": payload.get("last_report_path"),
                "location": payload.get("location"),
                "minConfidence": payload.get("min_confidence", 0.35),
            }

            stale = []
            with connected_clients_lock:
                sockets = list(connected_clients)

            for client in sockets:
                try:
                    await client.send(json.dumps(event))
                except Exception:
                    stale.append(client)

            if stale:
                with connected_clients_lock:
                    for s in stale:
                        connected_clients.discard(s)

            last_updated = updated_at

    logger.info(f"Starting server on port {WS_PORT}")
    async with websockets.serve(handle_connection, "0.0.0.0", WS_PORT):
        preload_task = None
        if PRELOAD_AUDIO_MODELS:
            preload_task = asyncio.create_task(_preload_audio_models_async())

        broadcaster = asyncio.create_task(broadcast_cv_events())
        try:
            await asyncio.Future()  # run forever
        finally:
            broadcaster.cancel()
            if preload_task is not None:
                preload_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
