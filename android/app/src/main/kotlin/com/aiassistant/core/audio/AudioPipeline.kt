package com.aiassistant.core.audio

import android.annotation.SuppressLint
import android.media.*
import android.os.Process
import com.aiassistant.core.config.ConfigManager
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableSharedFlow
import timber.log.Timber
import java.util.concurrent.ConcurrentLinkedQueue
import kotlin.math.max

class AudioPipeline(
    private val scope: CoroutineScope,
    private val onAudioChunk: (ByteArray) -> Unit
) {
    private var audioRecord: AudioRecord? = null
    private var audioTrack: AudioTrack? = null
    private var isRecording = false
    private var isPlaying = false
    
    private val playbackQueue = ConcurrentLinkedQueue<ByteArray>()
    
    private val sampleRate = ConfigManager.currentConfig.audioSampleRate
    private val channelConfig = AudioFormat.CHANNEL_IN_MONO
    private val audioFormat = AudioFormat.ENCODING_PCM_16BIT
    private val bufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)

    @SuppressLint("MissingPermission")
    private fun buildAudioRecord(audioSource: Int): AudioRecord {
        val minSize = max(bufferSize, sampleRate / 10)
        return AudioRecord(
            audioSource,
            sampleRate,
            channelConfig,
            audioFormat,
            minSize,
        )
    }

    @SuppressLint("MissingPermission")
    fun startRecording() {
        if (isRecording) return

        val preferredSources = listOf(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            MediaRecorder.AudioSource.MIC,
        )

        var initializedRecord: AudioRecord? = null
        for (source in preferredSources) {
            val candidate = try {
                buildAudioRecord(source)
            } catch (e: Exception) {
                Timber.w(e, "AudioRecord init exception for source=%s", source)
                null
            }

            if (candidate != null && candidate.state == AudioRecord.STATE_INITIALIZED) {
                initializedRecord = candidate
                Timber.i("AudioRecord initialized with source=%s", source)
                break
            }

            candidate?.release()
        }

        audioRecord = initializedRecord
        if (audioRecord == null) {
            Timber.e("AudioRecord initialization failed for all sources")
            return
        }

        isRecording = true
        audioRecord?.startRecording()

        scope.launch(Dispatchers.IO) {
            Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
            val chunkSizeBytes = (sampleRate * 2 * (ConfigManager.currentConfig.audioChunkMs / 1000.0)).toInt()
            val buffer = ByteArray(chunkSizeBytes)
            
            while (isRecording) {
                val read = audioRecord?.read(buffer, 0, buffer.size) ?: -1
                if (read > 0) {
                    onAudioChunk(buffer.copyOf(read))
                } else if (read == AudioRecord.ERROR_DEAD_OBJECT || read == AudioRecord.ERROR_INVALID_OPERATION) {
                    Timber.w("AudioRecord read error=%s", read)
                }
            }
        }
    }

    fun stopRecording() {
        isRecording = false
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
    }

    fun initPlayback() {
        val minTrackBuffer = AudioTrack.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_OUT_MONO,
            audioFormat
        )

        audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(audioFormat)
                    .setSampleRate(sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(minTrackBuffer * 2)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()

        audioTrack?.play()
        isPlaying = true
        
        scope.launch(Dispatchers.IO) {
            while (isPlaying) {
                val chunk = playbackQueue.poll()
                if (chunk != null) {
                    audioTrack?.write(chunk, 0, chunk.size)
                } else {
                    delay(10)
                }
            }
        }
    }

    fun enqueuePlayback(data: ByteArray) {
        playbackQueue.offer(data)
    }

    fun stopPlayback() {
        isPlaying = false
        audioTrack?.stop()
        audioTrack?.flush()
        audioTrack?.release()
        audioTrack = null
        playbackQueue.clear()
    }
}
