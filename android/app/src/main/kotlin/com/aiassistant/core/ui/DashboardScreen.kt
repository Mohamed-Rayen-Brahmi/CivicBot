package com.aiassistant.core.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun DashboardScreen(state: UIState, onToggleService: () -> Unit, onEmotionChange: (String) -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState())
    ) {
        Text(text = "CIVIC_BOT_V1.0", style = MaterialTheme.typography.headlineMedium, color = Color(0xFF00E5FF))
        Spacer(modifier = Modifier.height(16.dp))

        Card(
            modifier = Modifier
                .fillMaxWidth()
                .height(300.dp),
            colors = CardDefaults.cardColors(containerColor = Color.Black)
        ) {
            Box(contentAlignment = androidx.compose.ui.Alignment.Center) {
                BemoFace(emotion = state.emotion)
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            listOf("neutral", "happy", "sad", "angry", "thinking", "talking").forEach { emo ->
                TextButton(onClick = { onEmotionChange(emo) }) {
                    Text(emo.take(1).uppercase(), color = if (state.emotion == emo) Color(0xFF00E5FF) else Color.Gray)
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        Button(
            onClick = onToggleService,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (state.isRunning) Color.Red else Color(0xFF00E5FF),
                contentColor = Color.Black
            )
        ) {
            Text(if (state.isRunning) "STOP CIVIC_BOT" else "START CIVIC_BOT")
        }

        Spacer(modifier = Modifier.height(24.dp))

        Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFF1A1A1A))) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(text = "REAL-TIME STREAM", style = MaterialTheme.typography.labelLarge, color = Color(0xFF00E5FF))
                Spacer(modifier = Modifier.height(8.dp))
                Text(text = "STT: ${state.sttText}", color = Color.White)
                Text(text = "LLM: ${state.llmResponse}", color = Color.LightGray)
            }
        }
    }
}
