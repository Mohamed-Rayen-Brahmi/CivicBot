package com.aiassistant.core

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiassistant.core.service.AIServiceForegroundService
import com.aiassistant.core.ui.AISessionViewModel
import timber.log.Timber

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.ui.graphics.Color
import androidx.core.content.ContextCompat
import com.aiassistant.core.ui.*

class MainActivity : ComponentActivity() {

    private fun hasRequiredRuntimePermissions(): Boolean {
        val required = listOf(
            Manifest.permission.CAMERA,
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.ACCESS_FINE_LOCATION,
        )
        return required.all { permission ->
            ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED
        }
    }
    
    private val requestPermissionsLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        if (permissions.all { it.value }) {
            Timber.i("All permissions granted")
        } else {
            Timber.e("Permissions denied")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        }

        requestPermissionsLauncher.launch(
            arrayOf(
                Manifest.permission.CAMERA,
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.POST_NOTIFICATIONS,
                Manifest.permission.ACCESS_COARSE_LOCATION,
                Manifest.permission.ACCESS_FINE_LOCATION
            )
        )

        setContent {
            val viewModel: AISessionViewModel = viewModel()
            val state by viewModel.uiState.collectAsState()

            MaterialTheme(
                colorScheme = darkColorScheme(
                    primary = Color(0xFF00E5FF),
                    background = Color(0xFF0D0D0D),
                    surface = Color(0xFF1A1A1A)
                )
            ) {
                Scaffold(
                    bottomBar = {
                        NavigationBar(containerColor = Color(0xFF0D0D0D)) {
                            NavigationBarItem(
                                selected = state.currentTab == 0,
                                onClick = { viewModel.setTab(0) },
                                icon = { Icon(Icons.Default.Dashboard, contentDescription = null) },
                                label = { Text("DASHBOARD") },
                                colors = NavigationBarItemDefaults.colors(selectedIconColor = Color(0xFF00E5FF), selectedTextColor = Color(0xFF00E5FF))
                            )
                            NavigationBarItem(
                                selected = state.currentTab == 1,
                                onClick = { viewModel.setTab(1) },
                                icon = { Icon(Icons.Default.List, contentDescription = null) },
                                label = { Text("STATUS") },
                                colors = NavigationBarItemDefaults.colors(selectedIconColor = Color(0xFF00E5FF), selectedTextColor = Color(0xFF00E5FF))
                            )
                            NavigationBarItem(
                                selected = state.currentTab == 2,
                                onClick = { viewModel.setTab(2) },
                                icon = { Icon(Icons.Default.Settings, contentDescription = null) },
                                label = { Text("CONFIG") },
                                colors = NavigationBarItemDefaults.colors(selectedIconColor = Color(0xFF00E5FF), selectedTextColor = Color(0xFF00E5FF))
                            )
                        }
                    }
                ) { padding ->
                    Box(modifier = Modifier.padding(padding)) {
                        when (state.currentTab) {
                            0 -> DashboardScreen(
                                state = state,
                                onToggleService = {
                                    if (state.isRunning) {
                                        stopService(Intent(this@MainActivity, AIServiceForegroundService::class.java))
                                        viewModel.toggleService(false)
                                    } else {
                                        if (!hasRequiredRuntimePermissions()) {
                                            Timber.w("Missing required permissions, requesting again before service start")
                                            requestPermissionsLauncher.launch(
                                                arrayOf(
                                                    Manifest.permission.CAMERA,
                                                    Manifest.permission.RECORD_AUDIO,
                                                    Manifest.permission.POST_NOTIFICATIONS,
                                                    Manifest.permission.ACCESS_COARSE_LOCATION,
                                                    Manifest.permission.ACCESS_FINE_LOCATION,
                                                )
                                            )
                                            viewModel.toggleService(false)
                                            return@DashboardScreen
                                        }

                                        try {
                                            startForegroundService(Intent(this@MainActivity, AIServiceForegroundService::class.java))
                                            viewModel.toggleService(true)
                                        } catch (e: Exception) {
                                            Timber.e(e, "Failed to start CivicBot foreground service")
                                            viewModel.toggleService(false)
                                        }
                                    }
                                },
                                onEmotionChange = { viewModel.setEmotion(it) }
                            )
                            1 -> StatusScreen(state = state)
                            2 -> SettingsScreen(state = state, onConfigChange = { viewModel.updateConfig(it) })
                        }
                    }
                }
            }
        }
    }
}
