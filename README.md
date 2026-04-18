# CivicBot: Local Dual-Link AI Voice Pipeline

CivicBot is a high-performance, bidirectional AI voice and vision pipeline designed for real-time interaction between an Android endpoint and a local GPU-accelerated PC. It integrates state-of-the-art local models for Speech-to-Text (STT), Large Language Models (LLM), and Text-to-Speech (TTS) to provide a seamless, low-latency companion experience.

![CivicBot UI](https://img.shields.io/badge/Status-Stable-brightgreen)
![Platform-Android](https://img.shields.io/badge/Platform-Android-orange)
![Backend-Python](https://img.shields.io/badge/Backend-Python-blue)

---

## 🚀 Key Features

- **Local-First Processing**: No cloud dependencies for voice processing, ensuring privacy and speed.
- **Optimized Voice Pipeline**:
  - **STT**: [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) (Base model) for near-instant transcription.
  - **LLM**: Integrated with [Ollama](https://ollama.com/) (Recommended: `phi3:latest` or `llama3.2:1b`).
  - **TTS**: [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) for high-quality, human-like voice synthesis at 24kHz.
- **Smart Turn-Taking**: Intelligent silence detection (0.8s threshold) to prevent interruptions and ensure fluent conversation.
- **High-Volume Audio**: Hardware-level speakerphone routing and 1.5x software gain boost for clear outdoor usability.
- **Seamless Connectivity**: Ready-to-use with Tailscale mesh networks for secure remote access.

---

## 🛠️ System Architecture

1. **Android Endpoint (`/android`)**:
   - Built with Jetpack Compose and CameraX.
   - Captures 16kHz Mono PCM audio and YUV camera frames.
   - Streams data via WebSockets to the local server.
   - Optimized with R8/Proguard for minimal footprint.

2. **PC Backend (`server.py`)**:
   - Orchestrates the AI loop using `asyncio` and `websockets`.
   - Uses `ctranslate2` for GPU-accelerated Whisper inference.
   - Implements polyphase resampling for ultra-fast 24kHz -> 16kHz audio conversion.
   - Non-blocking LLM execution via thread pools to maintain UI responsiveness.

---

## 💻 Installation & Setup

### 1. Prerequisites
- **OS**: Windows (tested) or Linux.
- **GPU**: NVIDIA RTX 3050 (6GB VRAM) or higher recommended (CUDA 12.x supported).
- **Environment**: Python 3.9+, Android Studio (for mobile build).

### 2. Backend Setup
```bash
# Clone the repository
git clone <repo-url>
cd app-main

# Create virtual environment
python -m venv .venv
source .venv/Scripts/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start Ollama (ensure phi3 is pulled)
ollama pull phi3:latest
```

### 3. Android Setup
- Open the `/android` directory in **Android Studio**.
- Ensure **Tailscale** is running on both the phone and the PC.
- Build the APK:
  ```powershell
  $env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
  .\gradlew assembleDebug
  ```
- Install the resulting `CivicBot_v1.0.apk` on your device.

---

## 🏃 Running the Pipeline

1. **Start the AI Server**:
   ```bash
   python server.py
   ```
2. **Launch the App**:
   - Open **CivicBot** on your Android device.
   - Ensure the IP is set to your PC's Tailscale IP (Default: `100.81.46.110`).
   - Press **START CIVIC_BOT**.
3. **Interact**:
   - Speak naturally. The robot will listen, process your request through Phi-3, and respond with high-quality synthesized speech.

---

## 🐳 Run with Docker (Web UI + AI Backend)

This repository now includes:
- `Dockerfile.web` (serves the React UI)
- `Dockerfile.backend` (runs `server.py` + CV module)
- `docker-compose.yml` (starts both)

### 1) Configure `.env`

Edit `.env` and set:
- `ANDROID_CAMERA_URL=http://<your-android-tailscale-ip>:8080/stream`
- `ROBOFLOW_API_KEY=<your_key>`
- `ROBOFLOW_MODEL_URL=https://detect.roboflow.com/<your-model>/<version>`

`yolov8n.pt` is auto-downloaded at first backend start.

### 2) Start services

```bash
docker compose up --build -d
```

### Optional: run Ollama in Docker (low-memory profile)

If you only have around 2-3 GB free RAM, use a small model (`tinyllama:latest`) and run Ollama with constrained settings:

```bash
docker compose --profile with-ollama up --build -d
docker exec -it civicbot-ollama ollama pull tinyllama:latest
```

Then in `.env`, set:
- `OLLAMA_URL=http://civicbot-ollama:11434/api/generate`
- `MODEL_NAME=tinyllama:latest`
- `OLLAMA_KEEP_ALIVE=0`

`OLLAMA_KEEP_ALIVE=0` unloads the model between requests to reduce RAM pressure.

### 3) Open apps

- Web dashboard: `http://<pc-or-server-ip>:3000`
- Backend websocket: `ws://<pc-or-server-ip>:8765`

For Android, keep using your PC/Tailscale IP in the mobile app for websocket connection.

### 4) LLM note (Ollama)

By default, backend uses:
- `OLLAMA_URL=http://host.docker.internal:11434/api/generate`

So Ollama should be running on your host machine (outside container) unless you choose to run Ollama in Docker separately.

---

## ⚙️ Configuration

Settings can be tuned in `server.py`:
- `MODEL_NAME`: Change the LLM (e.g., `llama3.2:1b` for maximum speed).
- `keep_alive`: Set to `-1` to keep the model loaded in VRAM permanently.
- `turn_buffer`: Adjust the 0.8s silence threshold if you speak with longer pauses.

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
*Developed with ❤️ as a local AI companion experiment.*
