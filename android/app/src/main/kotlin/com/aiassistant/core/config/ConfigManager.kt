package com.aiassistant.core.config

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class AppConfig(
    val pcTailscaleHostname: String = "100.92.243.91",
    val wsPort: Int = 8765,
    val httpCameraPort: Int = 8080,
    val audioSampleRate: Int = 16000,
    val audioChunkMs: Int = 160,
    val cameraResolution: String = "720p",
    val cameraFps: Int = 15,
    val enableDebugLogging: Boolean = true,
    val showUiOverlays: Boolean = true,
    val wakelockTimeoutMs: Long = 300000,
    val useFrontCamera: Boolean = false,
    val useSpeakerphone: Boolean = true
)

object ConfigManager {
    private val json = Json { ignoreUnknownKeys = true }
    
    var currentConfig = AppConfig()
        private set

    fun loadConfig(jsonString: String?) {
        jsonString?.let {
            try {
                currentConfig = json.decodeFromString<AppConfig>(it)
            } catch (e: Exception) {
                // Fallback to defaults
            }
        }
    }

    fun updateConfig(newConfig: AppConfig) {
        currentConfig = newConfig
    }
}
