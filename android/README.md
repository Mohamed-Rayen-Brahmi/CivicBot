# Android AI Assistant Endpoint Setup Instructions

## 1. Tailscale Configuration
- Install Tailscale on the Android device and your PC.
- Ensure both are in the same Tailnet.
- Note the PC's Tailscale hostname (e.g., `my-pc.tail12345.ts.net`).
- Update `ConfigManager.kt` or the app's configuration with this hostname.

## 2. PC Backend Requirements
- A WebSocket server listening on port `8765`.
- The server should expect binary PCM (16kHz, 16-bit, mono) frames.
- The server should send back binary PCM frames for TTS.
- The server should send JSON frames for text:
  ```json
  {"type": "stt", "text": "What you said..."}
  {"type": "llm", "text": "AI response..."}
  ```

## 3. App Permissions
- On first launch, the app will request Camera, Microphone, and Notification permissions.
- Ensure "Appear on top" or "Background execution" is allowed if the system kills the service.

## 4. Testing the Camera Stream
- Once the session is started, open a browser on your PC.
- Navigate to `http://<android-tailscale-ip>:8080/stream`.
- You should see a live MJPEG stream from the device camera.

## 5. Known Android Quirks
- **Battery Optimization**: Disable battery optimization for this app to prevent the Foreground Service from being killed.
- **Audio Focus**: The app uses `VOICE_COMMUNICATION` which should duck other media, but some devices require manual focus handling if other apps are aggressive.
- **Android 14+**: The manifest explicitly declares `camera` and `microphone` service types. Do not remove these or the app will crash on startForeground.
