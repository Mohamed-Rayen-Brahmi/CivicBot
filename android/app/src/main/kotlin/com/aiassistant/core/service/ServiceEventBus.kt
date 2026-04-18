package com.aiassistant.core.service

import com.aiassistant.core.network.WSMessage
import com.aiassistant.core.network.WebSocketClientManager
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

sealed class ServiceEvent {
    data class TextReceived(val message: WSMessage) : ServiceEvent()
    data class ConnectionStateChanged(val state: WebSocketClientManager.ConnectionState) : ServiceEvent()
    data class AudioLevelChanged(val level: Float) : ServiceEvent()
}

object ServiceEventBus {
    private val _events = MutableSharedFlow<ServiceEvent>(extraBufferCapacity = 64)
    val events = _events.asSharedFlow()

    suspend fun emit(event: ServiceEvent) {
        _events.emit(event)
    }

    fun tryEmit(event: ServiceEvent) {
        _events.tryEmit(event)
    }
}
