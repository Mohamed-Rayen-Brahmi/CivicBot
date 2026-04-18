package com.aiassistant.core.network

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.aiassistant.core.config.ConfigManager
import io.ktor.http.*
import io.ktor.server.application.*
import io.ktor.server.engine.*
import io.ktor.server.netty.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import kotlinx.coroutines.channels.Channel
import io.ktor.utils.io.*
import timber.log.Timber
import java.io.ByteArrayOutputStream

class CameraStreamServer : ImageAnalysis.Analyzer {
    private val frameChannel = Channel<ByteArray>(Channel.CONFLATED)
    private var server: NettyApplicationEngine? = null
    var isRunning: Boolean = false
        private set
    
    private val boundary = "cameraframe"

    fun start(): Boolean {
        if (server != null) {
            isRunning = true
            return true
        }

        val port = ConfigManager.currentConfig.httpCameraPort
        return try {
            server = embeddedServer(Netty, port = port, host = "0.0.0.0") {
                routing {
                    get("/stream") {
                        call.respondBytesWriter(ContentType.parse("multipart/x-mixed-replace; boundary=$boundary")) {
                            while (true) {
                                val frame = frameChannel.receive()
                                writeStringUtf8("--$boundary\r\n")
                                writeStringUtf8("Content-Type: image/jpeg\r\n")
                                writeStringUtf8("Content-Length: ${frame.size}\r\n\r\n")
                                writeFully(frame)
                                writeStringUtf8("\r\n")
                                flush()
                            }
                        }
                    }
                }
            }.start(wait = false)
            isRunning = true
            Timber.i("Camera Server started on port $port")
            true
        } catch (e: Exception) {
            isRunning = false
            server = null
            Timber.e(e, "Camera Server failed to start on port $port")
            false
        }
    }

    override fun analyze(image: ImageProxy) {
        try {
            val jpeg = imageToJpeg(image)
            frameChannel.trySend(jpeg)
        } catch (e: Exception) {
            Timber.e(e, "Frame analysis failed")
        } finally {
            image.close()
        }
    }

    private fun imageToJpeg(image: ImageProxy): ByteArray {
        val planes = image.planes
        val yBuffer = planes[0].buffer
        val uBuffer = planes[1].buffer
        val vBuffer = planes[2].buffer

        val ySize = yBuffer.remaining()
        val uSize = uBuffer.remaining()
        val vSize = vBuffer.remaining()

        val nv21 = ByteArray(ySize + uSize + vSize)
        yBuffer.get(nv21, 0, ySize)
        vBuffer.get(nv21, ySize, vSize)
        uBuffer.get(nv21, ySize + vSize, uSize)

        val yuvImage = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
        val out = ByteArrayOutputStream()
        yuvImage.compressToJpeg(Rect(0, 0, image.width, image.height), 70, out)
        return out.toByteArray()
    }

    fun stop() {
        try {
            server?.stop(1000, 2000)
        } catch (_: Exception) {
        }
        server = null
        isRunning = false
    }
}
