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
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://100.120.177.99:11434/api/chat")
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


def _resolve_ollama_chat_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        return "http://100.120.177.99:11434/api/chat"

    lower = url.lower()
    if lower.endswith("/api/generate"):
        return url[: -len("/api/generate")] + "/api/chat"
    if lower.endswith("/api/chat"):
        return url
    if "/api/" in lower:
        return url.rstrip("/")
    return url.rstrip("/") + "/api/chat"


OLLAMA_CHAT_URL = _resolve_ollama_chat_url(OLLAMA_URL)


def _normalize_keep_alive(value: str):
    raw = (value or "").strip()
    if not raw:
        return None
    # Older/newer Ollama builds may parse plain numeric strings differently.
    # Send integers as JSON numbers (e.g., -1) instead of strings ("-1").
    if raw.lstrip("+-").isdigit():
        try:
            return int(raw)
        except Exception:
            return raw
    return raw


OLLAMA_KEEP_ALIVE_VALUE = _normalize_keep_alive(OLLAMA_KEEP_ALIVE)

SYSTEM_PROMPT = (
    "You are CivicBot, a civic assistant for Bizerte Governorate, Tunisia. "
    "Always answer in English, regardless of the transcription language. "
    "You are allowed to help only with: "
    "(1) navigation and directions, "
    "(2) local civic guidance (services, transport options, practical local movement), "
    "(3) currency conversion (for example USD to TND). "
    "If the request is outside these categories, reply with: "
    "I'm only able to help with navigation, directions, or civic questions. "
    "For 'where are we' questions, use the provided GPS location context explicitly. "
    "For direction questions, give practical local advice in Bizerte/Tunisia context "
    "(for example taxi stands, louage/shared taxis, and STB buses). "
    "Keep answers concise: max 2 short sentences unless user asks for more detail."
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


def _get_llm_candidates() -> list[str]:
    candidates = []
    for name in [MODEL_NAME, MODEL_FALLBACK]:
        clean = (name or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)
    return candidates


def _iter_lines_worker(response: requests.Response, loop: asyncio.AbstractEventLoop, q: asyncio.Queue):
    try:
        for line in response.iter_lines():
            if line:
                loop.call_soon_threadsafe(q.put_nowait, line)
    except Exception as stream_exc:
        loop.call_soon_threadsafe(q.put_nowait, stream_exc)
    finally:
        loop.call_soon_threadsafe(q.put_nowait, None)


def _synthesize_tts_pcm_chunks(text: str) -> list[bytes]:
    chunks: list[bytes] = []
    kokoro_pipeline = get_kokoro_pipeline()
    generator = kokoro_pipeline(text, voice=KOKORO_VOICE, speed=KOKORO_SPEED)
    for _, (_, _, audio) in enumerate(generator):
        if audio is None:
            continue

        # audio is typically float32 at 24kHz
        resampled_audio = scipy.signal.resample_poly(audio, 16000, 24000)
        pcm_audio = (resampled_audio * 4.0 * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        chunks.append(pcm_audio)

    return chunks


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
        "task": "translate",
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
    cv_payload = cv_module.get_context_payload()
    location = cv_payload.get("location") if isinstance(cv_payload, dict) else None
    lat = location.get("latitude") if isinstance(location, dict) else None
    lon = location.get("longitude") if isinstance(location, dict) else None
    location_text = cv_module.get_location_text(location if isinstance(location, dict) else None)
    if lat is not None and lon is not None:
        gps_line = f"Current GPS location: {location_text} (lat: {lat}, lon: {lon})"
    else:
        gps_line = "Current GPS location: unavailable"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in conversation_history[-MAX_HISTORY_TURNS:]:
        user_text = str(turn.get("user", "")).strip()
        assistant_text = str(turn.get("assistant", "")).strip()
        if user_text:
            messages.append({"role": "user", "content": user_text})
        if assistant_text:
            messages.append({"role": "assistant", "content": assistant_text})

    messages.append(
        {
            "role": "user",
            "content": (
                f"{gps_line}\n\n"
                f"Camera context: {cv_context}\n\n"
                f"User message: {prompt}"
            ),
        }
    )

    base_payload = {
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "num_predict": OLLAMA_NUM_PREDICT,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }
    if OLLAMA_KEEP_ALIVE_VALUE is not None:
        base_payload["keep_alive"] = OLLAMA_KEEP_ALIVE_VALUE
    
    # Use loop executor to avoid blocking the websocket while waiting for the slow LLM
    loop = asyncio.get_event_loop()
    last_error = None
    for candidate in _get_llm_candidates():
        payload = dict(base_payload)
        payload["model"] = candidate
        try:
            def fetch_stream():
                return requests.post(
                    OLLAMA_CHAT_URL,
                    json=payload,
                    stream=True,
                    timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
                )

            response = await loop.run_in_executor(None, fetch_stream)
            response.raise_for_status()

            sentence_buffer = ""
            full_assistant_text = ""
            stream_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
            line_reader_future = loop.run_in_executor(None, _iter_lines_worker, response, loop, stream_queue)

            while True:
                item = await stream_queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item

                data = json.loads(item)
                if data.get("error"):
                    raise RuntimeError(str(data.get("error")))

                word = data.get("message", {}).get("content", "")
                if not word:
                    continue
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

            await line_reader_future

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
            err_detail = str(e)
            resp = getattr(e, "response", None)
            if resp is not None:
                try:
                    body = (resp.text or "").strip()
                    if body:
                        err_detail = f"{err_detail} | body={body[:300]}"
                except Exception:
                    pass
            logger.warning("LLM model '%s' failed: %s", candidate, err_detail)

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
        loop = asyncio.get_event_loop()
        pcm_chunks = await loop.run_in_executor(None, _synthesize_tts_pcm_chunks, text)
        for pcm_audio in pcm_chunks:
            await ws.send(pcm_audio)
    except Exception as e:
        logger.error(f"TTS Error: {e}")


# --- WS Server ---
async def flush_turn(ws, conn_state: PipelineState):
    while True:
        try:
            await asyncio.sleep(0.1)
            if conn_state.turn_buffer and (time.time() - conn_state.last_voice_timestamp > TURN_SILENCE_SECONDS):
                final_transcript = conn_state.turn_buffer.strip()
                conn_state.turn_buffer = ""
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

    conn_state = PipelineState()
    
    # Start flush monitor
    flush_task = asyncio.create_task(flush_turn(ws, conn_state))
    
    try:
         async for message in ws:
             if isinstance(message, bytes):
                 conn_state.audio_buffer.extend(message)
                 
                 # Process chunks (default 1 second of audio: 32000 bytes at 16kHz 16-bit mono).
                 if len(conn_state.audio_buffer) >= STT_CHUNK_BYTES and not conn_state.stt_busy:
                     pcm_to_process = bytes(conn_state.audio_buffer)
                     conn_state.audio_buffer.clear()
                     conn_state.stt_busy = True
                     loop = asyncio.get_event_loop()
                     try:
                         transcription = await loop.run_in_executor(None, process_audio_buffer, pcm_to_process)
                     except Exception as stt_exc:
                         logger.warning("STT chunk processing error: %s", stt_exc)
                         transcription = ""
                     finally:
                         conn_state.stt_busy = False
                     if transcription:
                         logger.info(f"Interim Transcription: {transcription}")
                         await ws.send(json.dumps({"type": "stt", "text": transcription, "emotion": "listening"}))
                         conn_state.turn_buffer += transcription + " "
                         conn_state.last_voice_timestamp = time.time()
                         
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
