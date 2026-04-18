package com.aiassistant.core.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp

@Composable
fun StatusScreen(state: UIState) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState())
    ) {
        Text(
            text = "SYSTEM STATUS",
            style = MaterialTheme.typography.headlineSmall,
            color = Color(0xFF00E5FF)
        )
        Spacer(modifier = Modifier.height(16.dp))

        StatusCard(
            title = "CAMERA SERVER",
            status = if (state.isRunning) "STABLE" else "OFFLINE",
            icon = Icons.Default.Videocam,
            badge = "HTTP 8080",
            isActive = state.isRunning
        )

        StatusCard(
            title = "MICROPHONE",
            status = if (state.isRunning) "ACTIVE" else "IDLE",
            icon = Icons.Default.Mic,
            badge = "16kHz PCM",
            isActive = state.isRunning
        )

        StatusCard(
            title = "TAILSCALE",
            status = if (state.connectionStatus == com.aiassistant.core.network.WebSocketClientManager.ConnectionState.CONNECTED) "CONNECTED" else "DISCONNECTED",
            icon = Icons.Default.Public,
            badge = "TUNNEL",
            isActive = state.connectionStatus == com.aiassistant.core.network.WebSocketClientManager.ConnectionState.CONNECTED
        )

        StatusCard(
            title = "FOREGROUND SERVICE",
            status = if (state.isRunning) "RUNNING" else "STOPPED",
            icon = Icons.Default.Settings,
            badge = "PID: 4022", // Mock PID
            isActive = state.isRunning
        )

        if (state.connectionStatus == com.aiassistant.core.network.WebSocketClientManager.ConnectionState.ERROR) {
            AlertCard()
        }

        Spacer(modifier = Modifier.height(16.dp))
        LogConsole()
    }
}

@Composable
fun StatusCard(title: String, status: String, icon: ImageVector, badge: String, isActive: Boolean) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1A1A1A))
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(icon, contentDescription = null, tint = if (isActive) Color(0xFF00E5FF) else Color.Gray)
            Spacer(modifier = Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.labelSmall, color = Color.Gray)
                Text(status, style = MaterialTheme.typography.titleMedium, color = Color.White)
            }
            Surface(
                color = if (isActive) Color(0xFF004D40) else Color(0xFF37474F),
                shape = MaterialTheme.shapes.small
            ) {
                Text(
                    badge,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                    style = MaterialTheme.typography.labelSmall,
                    color = if (isActive) Color(0xFF00E5FF) else Color.LightGray
                )
            }
        }
    }
}

@Composable
fun AlertCard() {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF2C1A1A))
    ) {
        Row(modifier = Modifier.padding(16.dp)) {
            Icon(Icons.Default.Warning, contentDescription = null, tint = Color.Red)
            Spacer(modifier = Modifier.width(16.dp))
            Column {
                Text("SYSTEM ALERT: RECONNECT ATTEMPT", style = MaterialTheme.typography.labelMedium, color = Color.Red)
                Text("Connection lost. Retrying handshake...", style = MaterialTheme.typography.bodySmall, color = Color.LightGray)
            }
        }
    }
}

@Composable
fun LogConsole() {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .height(200.dp),
        colors = CardDefaults.cardColors(containerColor = Color.Black)
    ) {
        Column(modifier = Modifier.padding(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("SYSTEM_LOGS.EXE", style = MaterialTheme.typography.labelSmall, color = Color.Gray)
                Spacer(modifier = Modifier.weight(1f))
                Text("CLEAR", style = MaterialTheme.typography.labelSmall, color = Color.Gray)
            }
            Divider(color = Color(0xFF333333), modifier = Modifier.padding(vertical = 4.dp))
            Text("[SYS] Initializing CameraX...", color = Color.Green, style = MaterialTheme.typography.bodySmall)
            Text("[NET] Tailscale interface detected", color = Color.Cyan, style = MaterialTheme.typography.bodySmall)
            Text("[AUD] AudioRecord buffer allocated", color = Color.White, style = MaterialTheme.typography.bodySmall)
        }
    }
}
