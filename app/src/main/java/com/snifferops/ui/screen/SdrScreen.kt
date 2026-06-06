package com.snifferops.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.snifferops.model.SdrSignal
import com.snifferops.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SdrScreen(
    signals: List<SdrSignal>,
    connected: Boolean,
    hasPermission: Boolean,
    networkConnected: Boolean,
    networkHost: String,
    networkPort: String,
    awarenessSyncHost: String,
    awarenessSyncPort: String,
    awarenessSyncEnabled: Boolean,
    awarenessSyncConnected: Boolean,
    awarenessSyncStatus: String,
    awarenessSignalCount: Int,
    deviceName: String,
    scanning: Boolean,
    onStartScan: () -> Unit,
    onStopScan: () -> Unit,
    onNetworkEndpointChange: (String, String) -> Unit,
    onConnectNetwork: () -> Unit,
    onDisconnectNetwork: () -> Unit,
    onAwarenessEndpointChange: (String, String) -> Unit,
    onAwarenessSyncEnabledChange: (Boolean) -> Unit,
    onBack: () -> Unit
) {
    val sdrColor = Color(0xFF8B5CF6)
    var selectedSignal by remember { mutableStateOf<SdrSignal?>(null) }

    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text("SDR DETECTIONS", fontFamily = FontFamily.Monospace,
                        color = sdrColor, letterSpacing = 2.sp)
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
            modifier = Modifier.fillMaxSize().padding(padding).background(BackgroundDark)
        ) {
            // Dongle status
            Surface(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                shape = RoundedCornerShape(8.dp),
                color = if (connected) Color(0xFF0D2010) else SurfaceVariantDark
            ) {
                Row(
                    modifier = Modifier.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Icon(Icons.Default.Usb, "USB",
                        tint = if (connected) RadarGreen else OnSurfaceMuted)
                    Column {
                        Text(
                            when {
                                networkConnected -> "Network SDR: $deviceName"
                                connected && hasPermission -> "RTL-SDR: $deviceName"
                                connected -> "RTL-SDR Connected - permission needed"
                                else -> "RTL-SDR Dongle Not Connected"
                            },
                            color = if (networkConnected || connected && hasPermission) RadarGreen else OnSurfaceMuted,
                            fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                            fontWeight = FontWeight.Bold
                        )
                        if (networkConnected) {
                            Text("Streaming from rtl_tcp on your Windows machine",
                                color = OnSurfaceMuted.copy(0.6f), fontSize = 10.sp)
                        } else if (connected && !hasPermission) {
                            Text("Tap Scan and approve the Android USB permission prompt",
                                color = OnSurfaceMuted.copy(0.6f), fontSize = 10.sp)
                        } else if (!connected) {
                            Text("Plug in your RTL-SDR Blog V4 via USB-C OTG adapter",
                                color = OnSurfaceMuted.copy(0.6f), fontSize = 10.sp)
                        }
                    }
                }
            }

            NetworkSdrPanel(
                host = networkHost,
                port = networkPort,
                connected = networkConnected,
                onEndpointChange = onNetworkEndpointChange,
                onConnect = onConnectNetwork,
                onDisconnect = onDisconnectNetwork
            )

            AwarenessSyncPanel(
                host = awarenessSyncHost.ifBlank { networkHost },
                port = awarenessSyncPort,
                enabled = awarenessSyncEnabled,
                connected = awarenessSyncConnected,
                status = awarenessSyncStatus,
                knownCount = awarenessSignalCount,
                onEndpointChange = onAwarenessEndpointChange,
                onEnabledChange = onAwarenessSyncEnabledChange
            )

            if (networkConnected || connected && hasPermission) {
                ScanControlBar(
                    scanning = scanning, count = signals.size,
                    color = sdrColor, onStart = onStartScan, onStop = onStopScan
                )
            } else if (connected) {
                Button(
                    onClick = onStartScan,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = sdrColor)
                ) {
                    Text("REQUEST USB PERMISSION", fontFamily = FontFamily.Monospace)
                }
            }

            if (!connected && !networkConnected) {
                Column(
                    modifier = Modifier.fillMaxSize().padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically)
                ) {
                    Icon(Icons.Default.Radio, "SDR", tint = OnSurfaceMuted, modifier = Modifier.size(64.dp))
                    Text("Connect RTL-SDR Dongle", color = OnSurface, fontSize = 18.sp,
                        fontWeight = FontWeight.Bold)
                    Text(
                        "Plug your RTL-SDR Blog V4 dongle into the USB-C port using an OTG adapter. " +
                        "The app will automatically detect it and enable spectrum scanning.",
                        color = OnSurfaceMuted, fontSize = 13.sp
                    )
                    Text("Supported devices: RTL-SDR Blog V4, RTL2838, RTL2832, R820T, ezcap EzTV",
                        color = OnSurfaceMuted.copy(0.6f), fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace)
                }
            } else if (connected && !networkConnected && !hasPermission) {
                EmptyState("USB permission needed", "Approve the Android USB prompt to enable SDR scanning")
            } else if (signals.isEmpty()) {
                EmptyState("No measured SDR detections yet", "Tap Scan to measure catalog bands for peaks above the local noise floor")
            } else {
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(signals.sortedByDescending { it.power }) { signal ->
                        SdrSignalCard(signal, onClick = { selectedSignal = signal })
                    }
                }
                EstimatedInfoFooter()
            }
        }
    }

    selectedSignal?.let { signal ->
        SignalDetailDialog(
            title = signal.label.ifBlank { "RF signal" },
            subtitle = formatSignalFrequency(signal.frequency),
            rows = signal.detailRows(),
            onDismiss = { selectedSignal = null }
        )
    }
}

@Composable
private fun AwarenessSyncPanel(
    host: String,
    port: String,
    enabled: Boolean,
    connected: Boolean,
    status: String,
    knownCount: Int,
    onEndpointChange: (String, String) -> Unit,
    onEnabledChange: (Boolean) -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        shape = RoundedCornerShape(8.dp),
        color = SurfaceDark
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        "WINDOWS AWARENESS SYNC",
                        color = if (connected) RadarGreen else Color(0xFF22D3EE),
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 1.sp
                    )
                    Text(
                        "$status  |  $knownCount known",
                        color = OnSurfaceMuted,
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }
                Switch(checked = enabled, onCheckedChange = onEnabledChange)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = host,
                    onValueChange = { onEndpointChange(it, port) },
                    modifier = Modifier.weight(1f),
                    enabled = !enabled,
                    singleLine = true,
                    label = { Text("Windows IP") },
                    textStyle = LocalTextStyle.current.copy(fontFamily = FontFamily.Monospace, fontSize = 12.sp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = OnSurface,
                        unfocusedTextColor = OnSurface,
                        focusedBorderColor = Color(0xFF22D3EE),
                        unfocusedBorderColor = OnSurfaceMuted,
                        focusedLabelColor = Color(0xFF22D3EE),
                        unfocusedLabelColor = OnSurfaceMuted
                    )
                )
                OutlinedTextField(
                    value = port,
                    onValueChange = { onEndpointChange(host, it.filter(Char::isDigit).take(5)) },
                    modifier = Modifier.width(96.dp),
                    enabled = !enabled,
                    singleLine = true,
                    label = { Text("Port") },
                    textStyle = LocalTextStyle.current.copy(fontFamily = FontFamily.Monospace, fontSize = 12.sp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = OnSurface,
                        unfocusedTextColor = OnSurface,
                        focusedBorderColor = Color(0xFF22D3EE),
                        unfocusedBorderColor = OnSurfaceMuted,
                        focusedLabelColor = Color(0xFF22D3EE),
                        unfocusedLabelColor = OnSurfaceMuted
                    )
                )
            }
        }
    }
}

@Composable
private fun NetworkSdrPanel(
    host: String,
    port: String,
    connected: Boolean,
    onEndpointChange: (String, String) -> Unit,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        shape = RoundedCornerShape(8.dp),
        color = SurfaceDark
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                "WINDOWS NETWORK SDR",
                color = Color(0xFF8B5CF6),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = host,
                    onValueChange = { onEndpointChange(it, port) },
                    modifier = Modifier.weight(1f),
                    enabled = !connected,
                    singleLine = true,
                    label = { Text("Windows IP") },
                    textStyle = LocalTextStyle.current.copy(fontFamily = FontFamily.Monospace, fontSize = 12.sp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = OnSurface,
                        unfocusedTextColor = OnSurface,
                        focusedBorderColor = Color(0xFF8B5CF6),
                        unfocusedBorderColor = OnSurfaceMuted,
                        focusedLabelColor = Color(0xFF8B5CF6),
                        unfocusedLabelColor = OnSurfaceMuted
                    )
                )
                OutlinedTextField(
                    value = port,
                    onValueChange = { onEndpointChange(host, it.filter(Char::isDigit).take(5)) },
                    modifier = Modifier.width(96.dp),
                    enabled = !connected,
                    singleLine = true,
                    label = { Text("Port") },
                    textStyle = LocalTextStyle.current.copy(fontFamily = FontFamily.Monospace, fontSize = 12.sp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = OnSurface,
                        unfocusedTextColor = OnSurface,
                        focusedBorderColor = Color(0xFF8B5CF6),
                        unfocusedBorderColor = OnSurfaceMuted,
                        focusedLabelColor = Color(0xFF8B5CF6),
                        unfocusedLabelColor = OnSurfaceMuted
                    )
                )
            }
            Button(
                onClick = if (connected) onDisconnect else onConnect,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (connected) AlertRed else Color(0xFF8B5CF6)
                )
            ) {
                Icon(if (connected) Icons.Default.LinkOff else Icons.Default.Link, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(
                    if (connected) "DISCONNECT NETWORK SDR" else "CONNECT NETWORK SDR",
                    fontFamily = FontFamily.Monospace
                )
            }
        }
    }
}

@Composable
private fun SdrSignalCard(signal: SdrSignal, onClick: () -> Unit) {
    val sdrColor = Color(0xFF8B5CF6)
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = SurfaceDark,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Icon(Icons.Default.Radio, "SDR", tint = sdrColor, modifier = Modifier.size(28.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text("Type*: ${signal.label}", color = OnSurface, fontWeight = FontWeight.Medium, fontSize = 14.sp)
                Text(
                    formatSignalFrequency(signal.frequency),
                    color = sdrColor, fontSize = 13.sp,
                    fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold
                )
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("${signal.power.toInt()} dB", color = powerColor(signal.power),
                        fontSize = 11.sp, fontFamily = FontFamily.Monospace)
                    if (signal.modulation.isNotEmpty() && signal.modulation != "Unknown") {
                        Text(signal.modulation, color = OnSurfaceMuted, fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace)
                    }
                }
            }
        }
    }
}

private fun powerColor(power: Float) = when {
    power >= -60 -> AlertRed
    power >= -75 -> WarningOrange
    power >= -90 -> SuspiciousYellow
    else -> SafeGreen
}
