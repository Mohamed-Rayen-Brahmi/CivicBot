package com.aiassistant.core.service

import android.app.*
import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.IBinder
import android.os.Build
import android.os.PowerManager
import android.os.Looper
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.core.location.LocationListenerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.aiassistant.core.MainActivity
import com.aiassistant.core.audio.AudioPipeline
import com.aiassistant.core.network.CameraStreamServer
import com.aiassistant.core.network.WebSocketClientManager
import kotlinx.coroutines.*
import timber.log.Timber
import java.util.concurrent.Executors

class AIServiceForegroundService : Service(), LifecycleOwner {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    
    private lateinit var lifecycleRegistry: LifecycleRegistry
    
    private lateinit var audioPipeline: AudioPipeline
    private lateinit var wsManager: WebSocketClientManager
    private val cameraServer = CameraStreamServer()
    private lateinit var locationManager: LocationManager
    private var lastSentLocationAt = 0L
    private var locationHeartbeatJob: Job? = null
    
    private val cameraExecutor = Executors.newSingleThreadExecutor()

    private val locationListener = object : LocationListenerCompat {
        override fun onLocationChanged(location: Location) {
            handleLocation(location)
        }

        override fun onProviderEnabled(provider: String) {
            Timber.i("Location provider enabled: %s", provider)
        }

        override fun onProviderDisabled(provider: String) {
            Timber.w("Location provider disabled: %s", provider)
        }

    }

    override fun onCreate() {
        super.onCreate()
        lifecycleRegistry = LifecycleRegistry(this)
        lifecycleRegistry.currentState = Lifecycle.State.CREATED
        try {
            initManagers()
            startForegroundService()
        } catch (e: Exception) {
            Timber.e(e, "AIServiceForegroundService failed during onCreate; stopping service safely")
            stopSelf()
        }
    }

    override val lifecycle: Lifecycle
        get() = lifecycleRegistry

    private fun initManagers() {
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager

        wsManager = WebSocketClientManager(
            serviceScope,
            onTextReceived = { msg ->
                val text = msg.text?.trim()
                if (!text.isNullOrEmpty()) {
                    ServiceEventBus.tryEmit(ServiceEvent.TextReceived(msg))
                    Timber.d("Received text: %s", text)
                }
            },
            onAudioReceived = { audio ->
                audioPipeline.enqueuePlayback(audio)
            }
        )
        
        audioPipeline = AudioPipeline(serviceScope) { chunk ->
            wsManager.sendAudio(chunk)
        }

        serviceScope.launch {
            wsManager.connectionState.collect { state ->
                ServiceEventBus.emit(ServiceEvent.ConnectionStateChanged(state))
                if (state == WebSocketClientManager.ConnectionState.CONNECTED) {
                    sendLastKnownLocation(force = true)
                }
            }
        }
    }

    private fun startForegroundService() {
        lifecycleRegistry.currentState = Lifecycle.State.STARTED
        val channelId = "civicbot_service_channel"
        val channelName = "CivicBot Service"
        
        val channel = NotificationChannel(channelId, channelName, NotificationManager.IMPORTANCE_LOW)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)

        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("CivicBot Active")
            .setContentText("Streaming camera and audio...")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()

        startForeground(1, notification)

        acquireWakeLock()
        startCapture()
    }

    private fun startCapture() {
        val cameraStarted = cameraServer.start()
        if (!cameraStarted) {
            Timber.w("Camera HTTP stream failed to start; continuing with audio/websocket services")
        }

        try {
            wsManager.connect()
        } catch (e: Exception) {
            Timber.e(e, "WebSocket manager failed to start")
        }

        try {
            startLocationUpdates()
        } catch (e: Exception) {
            Timber.e(e, "Location updates failed to start")
        }

        try {
            audioPipeline.startRecording()
            audioPipeline.initPlayback()
        } catch (e: Exception) {
            Timber.e(e, "Audio pipeline failed to start")
        }

        configureSpeakerOutput(enable = true)

        // Bind CameraX
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            try {
                val cameraProvider = cameraProviderFuture.get()
                val imageAnalysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                imageAnalysis.setAnalyzer(cameraExecutor, cameraServer)

                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(
                    this,
                    if (com.aiassistant.core.config.ConfigManager.currentConfig.useFrontCamera) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA,
                    imageAnalysis
                )
                Timber.i("CameraX bound successfully")
            } catch (e: Exception) {
                Timber.e(e, "Camera binding failed")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun acquireWakeLock() {
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "AIAssistant:WakeLock")
        wakeLock?.acquire(3 * 60 * 60 * 1000L)
    }

    private fun hasLocationPermission(): Boolean {
        val fine = ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        return fine || coarse
    }

    private fun startLocationUpdates() {
        if (!hasLocationPermission()) {
            Timber.w("Location permission missing; GPS reporting disabled")
            return
        }

        try {
            locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let { handleLocation(it) }
            locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)?.let { handleLocation(it) }

            locationManager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER,
                5000L,
                5f,
                locationListener,
                Looper.getMainLooper(),
            )
            locationManager.requestLocationUpdates(
                LocationManager.NETWORK_PROVIDER,
                5000L,
                10f,
                locationListener,
                Looper.getMainLooper(),
            )
            Timber.i("Location updates started")

            // Keep a low-frequency heartbeat so backend still receives GPS
            // even when user is stationary and no new location callback arrives.
            locationHeartbeatJob?.cancel()
            locationHeartbeatJob = serviceScope.launch {
                while (isActive) {
                    delay(15000L)
                    sendLastKnownLocation(force = true)
                }
            }
        } catch (e: Exception) {
            Timber.e(e, "Failed to start location updates")
        }
    }

    private fun sendLastKnownLocation(force: Boolean = false) {
        if (!this::locationManager.isInitialized || !hasLocationPermission()) {
            return
        }

        try {
            val latest = locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)

            if (latest != null) {
                handleLocation(latest, force = force)
            }
        } catch (e: Exception) {
            Timber.w(e, "Unable to fetch last-known location for resend")
        }
    }

    private fun handleLocation(location: Location, force: Boolean = false) {
        val now = System.currentTimeMillis()
        if (!force && now - lastSentLocationAt < 4000L) {
            return
        }

        lastSentLocationAt = now
        wsManager.sendLocationUpdate(
            latitude = location.latitude,
            longitude = location.longitude,
            accuracyMeters = if (location.hasAccuracy()) location.accuracy else null,
            source = "android-phone",
        )
        Timber.i("Sent GPS to backend lat=%s lon=%s", location.latitude, location.longitude)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        lifecycleRegistry.currentState = Lifecycle.State.DESTROYED
        cameraServer.stop()
        locationHeartbeatJob?.cancel()
        try {
            if (this::locationManager.isInitialized) {
                locationManager.removeUpdates(locationListener)
            }
        } catch (_: Exception) {
        }
        wsManager.disconnect()
        audioPipeline.stopRecording()
        audioPipeline.stopPlayback()
        configureSpeakerOutput(enable = false)
        wakeLock?.release()
        serviceScope.cancel()
        cameraExecutor.shutdown()
    }

    private fun configureSpeakerOutput(enable: Boolean) {
        val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audioManager.mode = AudioManager.MODE_NORMAL

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (enable) {
                val speaker = audioManager.availableCommunicationDevices.firstOrNull {
                    it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
                }
                if (speaker != null) {
                    audioManager.setCommunicationDevice(speaker)
                }
            } else {
                audioManager.clearCommunicationDevice()
            }
        }

        // Deprecated but still useful on many OEM builds for forcing loudspeaker route.
        audioManager.isSpeakerphoneOn = enable
        Timber.i("Speaker output %s", if (enable) "enabled" else "disabled")
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
