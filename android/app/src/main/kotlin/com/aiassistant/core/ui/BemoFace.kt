package com.aiassistant.core.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlin.math.sin

@Composable
fun BemoFace(emotion: String, modifier: Modifier = Modifier) {
    val infiniteTransition = rememberInfiniteTransition(label = "bemo_system")
    
    // 1. Procedural Blinking Logic
    var isBlinking by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            delay((2000..5000).random().toLong())
            isBlinking = true
            delay(150)
            isBlinking = false
        }
    }

    val blinkScale by animateFloatAsState(
        targetValue = if (isBlinking) 0.1f else 1f,
        animationSpec = tween(100),
        label = "blink"
    )

    // 2. Breathing Animation (Subtle body movement)
    val breatheOffset by infiniteTransition.animateFloat(
        initialValue = -5f,
        targetValue = 5f,
        animationSpec = infiniteRepeatable(
            animation = tween(2500, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "breathe"
    )

    // 3. Emotion State Mapping
    val eyeHeightTarget = when (emotion) {
        "happy" -> 20f
        "sad", "angry" -> 45f
        "thinking" -> 15f
        "talking" -> 55f
        else -> 35f
    }

    val eyebrowAngleTarget = when (emotion) {
        "happy" -> -15f
        "angry" -> 20f
        "sad" -> -25f
        "thinking" -> 10f
        else -> 0f
    }

    val mouthPathProgress by animateFloatAsState(
        targetValue = if (emotion == "happy") 1f else if (emotion == "sad") -1f else 0f,
        animationSpec = spring(Spring.DampingRatioMediumBouncy),
        label = "mouth_shape"
    )

    val eyeHeight by animateFloatAsState(targetValue = eyeHeightTarget, animationSpec = spring(Spring.DampingRatioLowBouncy), label = "eye_h")
    val eyebrowAngle by animateFloatAsState(targetValue = eyebrowAngleTarget, animationSpec = spring(Spring.DampingRatioMediumBouncy), label = "brow_a")

    Canvas(modifier = modifier.fillMaxSize()) {
        val center = Offset(size.width / 2, size.height / 2 + breatheOffset)
        val eyeSpacing = 110f
        val eyeY = center.y - 40f
        val color = Color(0xFF00E5FF)
        val glowColor = color.copy(alpha = 0.3f)

        // --- DRAW EYES ---
        fun drawEye(offsetX: Float) {
            val rectSize = Size(50f, eyeHeight * blinkScale)
            val topLeft = Offset(center.x + offsetX - 25f, eyeY - rectSize.height / 2)
            
            // Outer Glow
            drawRoundRect(
                color = glowColor,
                topLeft = topLeft.copy(x = topLeft.x - 5f, y = topLeft.y - 5f),
                size = rectSize.copy(width = rectSize.width + 10f, height = rectSize.height + 10f),
                cornerRadius = CornerRadius(30f, 30f)
            )
            // Core Eye
            drawRoundRect(
                color = color,
                topLeft = topLeft,
                size = rectSize,
                cornerRadius = CornerRadius(25f, 25f)
            )
        }

        drawEye(-eyeSpacing) // Left
        drawEye(eyeSpacing)  // Right

        // --- DRAW EYEBROWS ---
        fun drawEyebrow(offsetX: Float, isLeft: Boolean) {
            val browWidth = 60f
            val browY = eyeY - 60f - (if (emotion == "thinking" && isLeft) 20f else 0f)
            val angleRad = Math.toRadians(eyebrowAngle.toDouble() * (if (isLeft) 1 else -1)).toFloat()
            
            val startX = center.x + offsetX - (browWidth / 2)
            val endX = center.x + offsetX + (browWidth / 2)
            
            val startY = browY - (Math.sin(angleRad.toDouble()) * (browWidth / 2)).toFloat()
            val endY = browY + (Math.sin(angleRad.toDouble()) * (browWidth / 2)).toFloat()

            drawLine(
                color = color,
                start = Offset(startX, startY),
                end = Offset(endX, endY),
                strokeWidth = 12f,
                cap = androidx.compose.ui.graphics.StrokeCap.Round
            )
        }

        drawEyebrow(-eyeSpacing, true)
        drawEyebrow(eyeSpacing, false)

        // --- DRAW MOUTH ---
        val mouthY = center.y + 90f
        val baseMouthWidth = 100f
        
        if (emotion == "talking") {
            // Video-like talking animation (Dynamic height + width)
            val talkCycle = sin(System.currentTimeMillis() / 80.0).toFloat()
            val dynamicHeight = 30f + (talkCycle * 20f)
            val dynamicWidth = baseMouthWidth + (talkCycle * 10f)
            
            drawRoundRect(
                color = color,
                topLeft = Offset(center.x - dynamicWidth / 2, mouthY - dynamicHeight / 2),
                size = Size(dynamicWidth, dynamicHeight),
                cornerRadius = CornerRadius(20f, 20f)
            )
        } else {
            // Path-based mouth for Happy/Sad/Neutral
            val path = Path().apply {
                val startX = center.x - baseMouthWidth / 2
                val endX = center.x + baseMouthWidth / 2
                val curveOffset = 40f * mouthPathProgress
                
                moveTo(startX, mouthY)
                quadraticBezierTo(
                    center.x, mouthY + curveOffset,
                    endX, mouthY
                )
            }
            drawPath(
                path = path,
                color = color,
                style = Stroke(width = 14f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
            )
        }
        
        // --- ADD SCANLINE EFFECT (Optional Tech Vibe) ---
        val scanlineY = (System.currentTimeMillis() % 4000) / 4000f * size.height
        drawLine(
            color = color.copy(alpha = 0.1f),
            start = Offset(0f, scanlineY),
            end = Offset(size.width, scanlineY),
            strokeWidth = 2f
        )
    }
}
