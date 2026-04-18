package com.aiassistant.core.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aiassistant.core.config.AppConfig

@Composable
fun SettingsScreen(state: UIState, onConfigChange: (AppConfig) -> Unit) {
    var hostname by remember { mutableStateOf(state.config.pcTailscaleHostname) }
    var wsPort by remember { mutableStateOf(state.config.wsPort.toString()) }
    var camPort by remember { mutableStateOf(state.config.httpCameraPort.toString()) }
    var debugEnabled by remember { mutableStateOf(state.config.enableDebugLogging) }
    var wakelockEnabled by remember { mutableStateOf(true) }
    var useFrontCamera by remember { mutableStateOf(state.config.useFrontCamera) }
    var useSpeakerphone by remember { mutableStateOf(state.config.useSpeakerphone) }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState())
    ) {
        Text(
            text = "SYSTEM CONFIG",
            style = MaterialTheme.typography.headlineSmall,
            color = Color(0xFF00E5FF)
        )
        Text(
            text = "ENVIRONMENT: LOCAL_PRODUCTION",
            style = MaterialTheme.typography.labelSmall,
            color = Color.Gray
        )
        Spacer(modifier = Modifier.height(24.dp))

        ConfigSection(title = "NETWORK TOPOLOGY") {
            OutlinedTextField(
                value = hostname,
                onValueChange = { hostname = it },
                label = { Text("PC TAILSCALE HOSTNAME") },
                modifier = Modifier.fillMaxWidth(),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Color(0xFF00E5FF),
                    unfocusedBorderColor = Color.Gray
                )
            )
            Spacer(modifier = Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = wsPort,
                    onValueChange = { wsPort = it },
                    label = { Text("WS PORT") },
                    modifier = Modifier.weight(1f),
                    colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Color(0xFF00E5FF))
                )
                Spacer(modifier = Modifier.width(8.dp))
                OutlinedTextField(
                    value = camPort,
                    onValueChange = { camPort = it },
                    label = { Text("CAMERA PORT") },
                    modifier = Modifier.weight(1f),
                    colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Color(0xFF00E5FF))
                )
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        ConfigSection(title = "KERNEL DIAGNOSTICS & UI") {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("ENABLE DEBUG LOGGING", color = Color.White)
                Switch(checked = debugEnabled, onCheckedChange = { debugEnabled = it }, colors = SwitchDefaults.colors(checkedThumbColor = Color(0xFF00E5FF)))
            }
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("WAKELOCK", color = Color.White)
                Switch(checked = wakelockEnabled, onCheckedChange = { wakelockEnabled = it }, colors = SwitchDefaults.colors(checkedThumbColor = Color(0xFF00E5FF)))
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        ConfigSection(title = "HARDWARE") {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("USE FRONT CAMERA", color = Color.White)
                Switch(checked = useFrontCamera, onCheckedChange = { useFrontCamera = it }, colors = SwitchDefaults.colors(checkedThumbColor = Color(0xFF00E5FF)))
            }
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("AUDIO OUTPUT VIA SPEAKER", color = Color.White)
                Switch(checked = useSpeakerphone, onCheckedChange = { useSpeakerphone = it }, colors = SwitchDefaults.colors(checkedThumbColor = Color(0xFF00E5FF)))
            }
        }

        Spacer(modifier = Modifier.height(32.dp))

        Button(
            onClick = {
                onConfigChange(
                    state.config.copy(
                        pcTailscaleHostname = hostname,
                        wsPort = wsPort.toIntOrNull() ?: 8765,
                        httpCameraPort = camPort.toIntOrNull() ?: 8080,
                        enableDebugLogging = debugEnabled,
                        useFrontCamera = useFrontCamera,
                        useSpeakerphone = useSpeakerphone
                    )
                )
            },
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF00E5FF), contentColor = Color.Black)
        ) {
            Text("SAVE & RESTART SERVICE")
        }
    }
}

@Composable
fun ConfigSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(title, style = MaterialTheme.typography.labelMedium, color = Color(0xFF00E5FF))
        Spacer(modifier = Modifier.height(8.dp))
        Card(
            colors = CardDefaults.cardColors(containerColor = Color(0xFF1A1A1A)),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                content()
            }
        }
    }
}
