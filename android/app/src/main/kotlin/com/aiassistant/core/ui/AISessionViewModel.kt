package com.aiassistant.core.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiassistant.core.network.WebSocketClientManager
import com.aiassistant.core.service.ServiceEvent
import com.aiassistant.core.service.ServiceEventBus
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
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

    // Batch high-frequency text updates to lower Compose recomposition churn.
    private var pendingSttText: String? = null
    private var pendingLlmText: String? = null
    private var pendingEmotion: String? = null
    private var sttFlushJob: Job? = null
    private var llmFlushJob: Job? = null

    init {
        viewModelScope.launch {
            ServiceEventBus.events.collect { event ->
                when (event) {
                    is ServiceEvent.TextReceived -> {
                        val msg = event.message
                        if (msg.type == "stt") {
                            queueTranscription(msg.text ?: "")
                        } else if (msg.type == "llm") {
                            queueLLMResponse(msg.text ?: "", msg.emotion)
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
        if (_uiState.value.connectionStatus == status) return
        _uiState.value = _uiState.value.copy(connectionStatus = status)
    }

    fun addTranscription(text: String) {
        if (_uiState.value.sttText == text) return
        _uiState.value = _uiState.value.copy(sttText = text)
    }

    fun updateLLMResponse(text: String, emotion: String? = null) {
        val nextEmotion = emotion ?: _uiState.value.emotion
        if (_uiState.value.llmResponse == text && _uiState.value.emotion == nextEmotion) return
        _uiState.value = _uiState.value.copy(llmResponse = text, emotion = nextEmotion)
    }

    private fun queueTranscription(text: String) {
        pendingSttText = text
        if (sttFlushJob?.isActive == true) return
        sttFlushJob = viewModelScope.launch {
            while (true) {
                delay(120)
                val value = pendingSttText ?: break
                pendingSttText = null
                addTranscription(value)
                if (pendingSttText == null) break
            }
        }
    }

    private fun queueLLMResponse(text: String, emotion: String?) {
        pendingLlmText = text
        pendingEmotion = emotion ?: pendingEmotion
        if (llmFlushJob?.isActive == true) return
        llmFlushJob = viewModelScope.launch {
            while (true) {
                delay(120)
                val value = pendingLlmText ?: break
                val emo = pendingEmotion
                pendingLlmText = null
                pendingEmotion = null
                updateLLMResponse(value, emo)
                if (pendingLlmText == null) break
            }
        }
    }

    fun setEmotion(emotion: String) {
        _uiState.value = _uiState.value.copy(emotion = emotion)
    }

    fun toggleService(running: Boolean) {
        _uiState.value = _uiState.value.copy(isRunning = running)
    }

    override fun onCleared() {
        sttFlushJob?.cancel()
        llmFlushJob?.cancel()
        super.onCleared()
    }
}
