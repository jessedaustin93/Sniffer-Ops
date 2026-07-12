package com.ethrox.detect.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ethrox.detect.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SyncScreen(
    host: String,
    port: String,
    connected: Boolean,
    syncing: Boolean,
    status: String,
    compactionReadyCount: Int,
    knownSignalCount: Int,
    onAwarenessEndpointChange: (String, String) -> Unit,
    onConnectAwarenessSync: () -> Unit,
    onSyncAwarenessNow: () -> Unit,
    onCompactAwareness: () -> Unit,
    onBack: () -> Unit
) {
    val syncColor = Color(0xFF22D3EE)
    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "LINUX HUB SYNC",
                        fontFamily = FontFamily.Monospace,
                        color = syncColor,
                        letterSpacing = 2.sp
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, "Back", tint = OnSurface)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SurfaceDark)
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(BackgroundDark)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(10.dp),
                color = SurfaceDark
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            Icons.Default.Sync,
                            contentDescription = null,
                            tint = if (connected) RadarGreen else syncColor
                        )
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(
                                if (connected) "LINUX HUB CONNECTED" else "LINUX HUB VIA TAILSCALE",
                                color = if (connected) RadarGreen else syncColor,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold
                            )
                            Text(
                                "$status  |  $knownSignalCount known",
                                color = OnSurfaceMuted,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 11.sp
                            )
                        }
                    }

                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = host,
                            onValueChange = { onAwarenessEndpointChange(it, port) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            label = { Text("Hub Tailscale host") }
                        )
                        OutlinedTextField(
                            value = port,
                            onValueChange = {
                                onAwarenessEndpointChange(host, it.filter(Char::isDigit).take(5))
                            },
                            modifier = Modifier.width(96.dp),
                            singleLine = true,
                            label = { Text("Port") }
                        )
                    }

                    Button(
                        onClick = onConnectAwarenessSync,
                        enabled = !syncing && host.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (connected) RadarGreen else Color(0xFF0D84FF),
                            contentColor = Color.Black
                        )
                    ) {
                        Icon(Icons.Default.Link, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("CONNECT", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                    }

                    Button(
                        onClick = onSyncAwarenessNow,
                        enabled = !syncing && host.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = syncColor, contentColor = Color.Black)
                    ) {
                        Icon(Icons.Default.Sync, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            if (syncing) "SENDING STORED HISTORY" else "SEND TO LINUX HUB",
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold
                        )
                    }

                    Button(
                        onClick = onCompactAwareness,
                        enabled = !syncing && compactionReadyCount > 0,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = RadarGreen,
                            contentColor = Color.Black,
                            disabledContainerColor = Color(0xFF263238),
                            disabledContentColor = OnSurfaceMuted
                        )
                    ) {
                        Icon(Icons.Default.Storage, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            if (compactionReadyCount > 0) {
                                "COMPACT PHONE ($compactionReadyCount CONFIRMED)"
                            } else {
                                "COMPACT PHONE (SEND + CONFIRM FIRST)"
                            },
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp
                        )
                    }
                }
            }

            Text(
                "The phone records independently. Enter the Linux hub's Tailscale address locally. Compaction unlocks only after the hub confirms assimilation.",
                color = OnSurfaceMuted,
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp
            )
        }
    }
}
