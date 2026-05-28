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
import com.snifferops.model.SdrSignal
import com.snifferops.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SdrScreen(
    signals: List<SdrSignal>,
    connected: Boolean,
    deviceName: String,
    scanning: Boolean,
    onStartScan: () -> Unit,
    onStopScan: () -> Unit,
    onBack: () -> Unit
) {
    val sdrColor = Color(0xFF8B5CF6)

    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text("SDR SCANNER", fontFamily = FontFamily.Monospace,
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
                            if (connected) "RTL-SDR: $deviceName" else "RTL-SDR Dongle Not Connected",
                            color = if (connected) RadarGreen else OnSurfaceMuted,
                            fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                            fontWeight = FontWeight.Bold
                        )
                        if (!connected) {
                            Text("Plug in your RTL4 dongle via USB-C OTG adapter",
                                color = OnSurfaceMuted.copy(0.6f), fontSize = 10.sp)
                        }
                    }
                }
            }

            if (connected) {
                ScanControlBar(
                    scanning = scanning, count = signals.size,
                    color = sdrColor, onStart = onStartScan, onStop = onStopScan
                )
            }

            if (!connected) {
                Column(
                    modifier = Modifier.fillMaxSize().padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically)
                ) {
                    Icon(Icons.Default.Radio, "SDR", tint = OnSurfaceMuted, modifier = Modifier.size(64.dp))
                    Text("Connect RTL-SDR Dongle", color = OnSurface, fontSize = 18.sp,
                        fontWeight = FontWeight.Bold)
                    Text(
                        "Plug your RTL2838/RTL4 SDR dongle into the USB-C port using an OTG adapter. " +
                        "The app will automatically detect it and enable spectrum scanning.",
                        color = OnSurfaceMuted, fontSize = 13.sp
                    )
                    Text("Supported devices: RTL2838, RTL2832, R820T, ezcap EzTV",
                        color = OnSurfaceMuted.copy(0.6f), fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace)
                }
            } else if (signals.isEmpty()) {
                EmptyState("No signals detected yet", "Tap Scan to begin sweeping frequencies")
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(signals.sortedByDescending { it.power }) { signal ->
                        SdrSignalCard(signal)
                    }
                }
            }
        }
    }
}

@Composable
private fun SdrSignalCard(signal: SdrSignal) {
    val sdrColor = Color(0xFF8B5CF6)
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
            Icon(Icons.Default.Radio, "SDR", tint = sdrColor, modifier = Modifier.size(28.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(signal.label, color = OnSurface, fontWeight = FontWeight.Medium, fontSize = 14.sp)
                Text(
                    formatFrequency(signal.frequency),
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

private fun formatFrequency(hz: Long): String = when {
    hz >= 1_000_000_000L -> "${"%.3f".format(hz / 1_000_000_000.0)} GHz"
    hz >= 1_000_000L -> "${"%.3f".format(hz / 1_000_000.0)} MHz"
    hz >= 1_000L -> "${"%.1f".format(hz / 1_000.0)} kHz"
    else -> "$hz Hz"
}

private fun powerColor(power: Float) = when {
    power >= -60 -> AlertRed
    power >= -75 -> WarningOrange
    power >= -90 -> SuspiciousYellow
    else -> SafeGreen
}
