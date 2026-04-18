package com.aiassistant.core.network

import com.aiassistant.core.config.ConfigManager
import io.ktor.client.*
import io.ktor.client.plugins.websocket.*
import io.ktor.http.*
import io.ktor.websocket.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import timber.log.Timber

@Serializable
data class WSMessage(
    val type: String,
    val text: String? = null,
    val emotion: String? = "neutral",
    val timestamp: Long = System.currentTimeMillis()
)

class WebSocketClientManager(
    private val scope: CoroutineScope,
    private val onTextReceived: (WSMessage) -> Unit,
    private val onAudioReceived: (ByteArray) -> Unit
) {
    private val client = HttpClient {
        install(WebSockets)
    }
    
    private var session: DefaultClientWebSocketSession? = null
    val connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    private val json = Json { ignoreUnknownKeys = true }
    
    enum class ConnectionState { DISCONNECTED, CONNECTING, CONNECTED, ERROR }

    fun connect() {
        scope.launch {
            val config = ConfigManager.currentConfig
            val host = config.pcTailscaleHostname
            val port = config.wsPort
            
            while (isActive) {
                try {
                    connectionState.value = ConnectionState.CONNECTING
                    client.webSocket(method = HttpMethod.Get, host = host, port = port, path = "/") {
                        session = this
                        connectionState.value = ConnectionState.CONNECTED
                        Timber.i("WebSocket Connected to $host:$port")
                        
                        for (frame in incoming) {
                            when (frame) {
                                is Frame.Text -> {
                                    try {
                                        val msg = json.decodeFromString<WSMessage>(frame.readText())
                                        onTextReceived(msg)
                                    } catch (parseEx: Exception) {
                                        Timber.w(parseEx, "Ignoring non-chat JSON frame from backend")
                                    }
                                }
                                is Frame.Binary -> {
                                    onAudioReceived(frame.readBytes())
                                }
                                else -> {}
                            }
                        }
                    }
                } catch (e: Exception) {
                    Timber.e(e, "WebSocket Connection Failed")
                    connectionState.value = ConnectionState.ERROR
                    delay(5000) // Exponential backoff would be better, but 5s is safe
                } finally {
                    connectionState.value = ConnectionState.DISCONNECTED
                    session = null
                }
            }
        }
    }

    fun sendAudio(data: ByteArray) {
        scope.launch {
            try {
                session?.send(Frame.Binary(true, data))
            } catch (e: Exception) {
                Timber.e(e, "Failed to send audio frame")
            }
        }
    }

    fun sendText(text: String) {
        scope.launch {
            try {
                session?.send(Frame.Text(text))
            } catch (e: Exception) {
                Timber.e(e, "Failed to send text frame")
            }
        }
    }

    fun sendLocationUpdate(latitude: Double, longitude: Double, accuracyMeters: Float?, source: String = "android") {
        val payload = buildJsonObject {
            put("type", "location")
            put("source", source)
            put("latitude", latitude)
            put("longitude", longitude)
            if (accuracyMeters != null) {
                put("accuracy", accuracyMeters)
            }
            put("timestamp", System.currentTimeMillis())
        }.toString()

        sendText(payload)
    }

    fun disconnect() {
        scope.launch {
            session?.close()
            session = null
        }
    }
}
