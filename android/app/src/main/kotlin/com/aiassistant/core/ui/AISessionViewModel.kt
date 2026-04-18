package com.aiassistant.core.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiassistant.core.network.WebSocketClientManager
import com.aiassistant.core.service.ServiceEvent
import com.aiassistant.core.service.ServiceEventBus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

data class UIState(
    val connectionStatus: WebSocketClientManager.ConnectionState = WebSocketClientManager.ConnectionState.DISCONNECTED,
    val sttText: String = "",
    val llmResponse: String = "",
    val emotion: String = "neutral",
    val isRunning: Boolean = false,
    val audioLevel: Float = 0f,
    val currentTab: Int = 0,
    val config: com.aiassistant.core.config.AppConfig = com.aiassistant.core.config.ConfigManager.currentConfig
)

class AISessionViewModel : ViewModel() {
    private val _uiState = MutableStateFlow(UIState())
    val uiState: StateFlow<UIState> = _uiState

    init {
        viewModelScope.launch {
            ServiceEventBus.events.collect { event ->
                when (event) {
                    is ServiceEvent.TextReceived -> {
                        val msg = event.message
                        if (msg.type == "stt") {
                            addTranscription(msg.text ?: "")
                        } else if (msg.type == "llm") {
                            updateLLMResponse(msg.text ?: "", msg.emotion)
                        }
                    }
                    is ServiceEvent.ConnectionStateChanged -> {
                        updateConnectionStatus(event.state)
                    }
                    is ServiceEvent.AudioLevelChanged -> {
                        _uiState.value = _uiState.value.copy(audioLevel = event.level)
                    }
                }
            }
        }
    }

    fun setTab(index: Int) {
        _uiState.value = _uiState.value.copy(currentTab = index)
    }

    fun updateConfig(newConfig: com.aiassistant.core.config.AppConfig) {
        _uiState.value = _uiState.value.copy(config = newConfig)
        com.aiassistant.core.config.ConfigManager.updateConfig(newConfig)
    }

    fun updateConnectionStatus(status: WebSocketClientManager.ConnectionState) {
        _uiState.value = _uiState.value.copy(connectionStatus = status)
    }

    fun addTranscription(text: String) {
        _uiState.value = _uiState.value.copy(sttText = text)
    }

    fun updateLLMResponse(text: String, emotion: String? = null) {
        _uiState.value = _uiState.value.copy(
            llmResponse = text,
            emotion = emotion ?: _uiState.value.emotion
        )
    }

    fun setEmotion(emotion: String) {
        _uiState.value = _uiState.value.copy(emotion = emotion)
    }

    fun toggleService(running: Boolean) {
        _uiState.value = _uiState.value.copy(isRunning = running)
    }
}
