package com.snifferops.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.snifferops.model.SignalDevice
import com.snifferops.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WifiScreen(
    devices: List<SignalDevice>,
    scanning: Boolean,
    onStartScan: () -> Unit,
    onStopScan: () -> Unit,
    onTriggerScan: () -> Unit,
    onBack: () -> Unit
) {
    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text("WiFi SCANNER", fontFamily = FontFamily.Monospace,
                        color = RadarGreen, letterSpacing = 2.sp)
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, "Back", tint = OnSurface)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SurfaceDark),
                actions = {
                    IconButton(onClick = onTriggerScan) {
                        Icon(Icons.Default.Refresh, "Refresh", tint = RadarGreen)
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).background(BackgroundDark)
        ) {
            // Scan control bar
            ScanControlBar(
                scanning = scanning,
                count = devices.size,
                color = RadarGreen,
                onStart = onStartScan,
                onStop = onStopScan
            )

            if (devices.isEmpty()) {
                EmptyState("No WiFi networks detected", "Tap scan to search for nearby networks")
            } else {
                val sorted = devices.sortedByDescending { it.signalStrength }
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(sorted, key = { it.id }) { device ->
                        WifiDeviceCard(device = device)
                    }
                }
            }
        }
    }
}

@Composable
private fun WifiDeviceCard(device: SignalDevice) {
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = SurfaceDark,
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // Signal strength indicator
            SignalBars(strength = device.signalStrength, color = device.threatLevel.toColor())

            Column(modifier = Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        device.name,
                        color = OnSurface,
                        fontWeight = FontWeight.Medium,
                        fontSize = 14.sp,
                        maxLines = 1
                    )
                    ThreatBadge(level = device.threatLevel)
                }
                Text(device.address, color = OnSurfaceMuted, fontSize = 11.sp,
                    fontFamily = FontFamily.Monospace)
                if (device.manufacturer.isNotEmpty() && device.manufacturer != "Unknown") {
                    Text(device.manufacturer, color = TacticalBlue, fontSize = 11.sp)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("${device.signalStrength} dBm", color = OnSurfaceMuted, fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace)
                    if (device.channel > 0) {
                        Text("Ch ${device.channel}", color = OnSurfaceMuted, fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace)
                    }
                    Icon(
                        if (device.isEncrypted) Icons.Default.Lock else Icons.Default.LockOpen,
                        "Encrypted",
                        tint = if (device.isEncrypted) SafeGreen else WarningOrange,
                        modifier = Modifier.size(14.dp)
                    )
                }
                if (device.deviceClass.isNotEmpty()) {
                    Text(device.deviceClass, color = WarningOrange, fontSize = 10.sp)
                }
            }
        }
    }
}
