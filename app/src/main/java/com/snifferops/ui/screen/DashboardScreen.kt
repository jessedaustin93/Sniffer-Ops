package com.snifferops.ui.screen

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.snifferops.ui.Screen
import com.snifferops.ui.theme.*
import com.snifferops.viewmodel.AppState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    state: AppState,
    onNavigate: (Screen) -> Unit,
    onStartScan: () -> Unit,
    onStopScan: () -> Unit,
    onClearData: () -> Unit
) {
    val summary = state.summary

    // Radar sweep animation
    val infiniteTransition = rememberInfiniteTransition(label = "radar")
    val sweepAngle by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(3000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "sweep"
    )

    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "SNIFFER OPS",
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = RadarGreen,
                        fontSize = 20.sp,
                        letterSpacing = 4.sp
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = SurfaceDark
                ),
                actions = {
                    if (summary.alertCount > 0) {
                        BadgedBox(badge = {
                            Badge(containerColor = AlertRed) { Text("${summary.alertCount}") }
                        }) {
                            IconButton(onClick = { onNavigate(Screen.Alerts) }) {
                                Icon(Icons.Default.Warning, "Alerts", tint = AlertRed)
                            }
                        }
                    }
                    IconButton(onClick = onClearData) {
                        Icon(Icons.Default.Delete, "Clear", tint = OnSurfaceMuted)
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .background(BackgroundDark)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Radar display + status
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // Radar circle
                Box(
                    modifier = Modifier
                        .size(120.dp)
                        .clip(CircleShape)
                        .background(Color(0xFF0A1A0A))
                        .border(2.dp, RadarGreen.copy(alpha = 0.5f), CircleShape),
                    contentAlignment = Alignment.Center
                ) {
                    // Concentric circles
                    Box(modifier = Modifier.size(80.dp).clip(CircleShape)
                        .border(1.dp, RadarGreen.copy(0.3f), CircleShape))
                    Box(modifier = Modifier.size(40.dp).clip(CircleShape)
                        .border(1.dp, RadarGreen.copy(0.3f), CircleShape))
                    // Sweep line (simplified as rotation)
                    if (state.scanActive) {
                        Box(
                            modifier = Modifier
                                .size(120.dp)
                                .rotate(sweepAngle)
                        ) {
                            Box(
                                modifier = Modifier
                                    .width(2.dp)
                                    .height(60.dp)
                                    .align(Alignment.TopCenter)
                                    .background(
                                        Brush.verticalGradient(
                                            colors = listOf(
                                                RadarGreen.copy(alpha = 0.8f),
                                                Color.Transparent
                                            )
                                        )
                                    )
                            )
                        }
                    }
                    Text(
                        if (state.scanActive) "LIVE" else "IDLE",
                        color = if (state.scanActive) RadarGreen else OnSurfaceMuted,
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold
                    )
                }

                // Status stats
                Column(
                    modifier = Modifier.weight(1f).padding(start = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    StatusRow("WIFI", summary.wifiCount, RadarGreen)
                    StatusRow("BT/BLE", summary.bluetoothCount + summary.bleCount, TacticalBlue)
                    StatusRow("CELL", summary.cellCount, WarningOrange)
                    StatusRow("SDR", summary.sdrCount, Color(0xFF8B5CF6))
                    StatusRow("ALERTS", summary.alertCount, AlertRed)
                }
            }

            // SDR status badge
            SdrStatusBadge(connected = summary.sdrConnected, deviceName = state.sdrDeviceName)

            // BIG SCAN BUTTON
            Button(
                onClick = if (state.scanActive) onStopScan else onStartScan,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(64.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (state.scanActive) AlertRed else RadarGreen,
                    contentColor = Color.Black
                ),
                shape = RoundedCornerShape(8.dp)
            ) {
                Icon(
                    if (state.scanActive) Icons.Default.Stop else Icons.Default.Search,
                    contentDescription = null,
                    modifier = Modifier.size(24.dp)
                )
                Spacer(Modifier.width(12.dp))
                Text(
                    if (state.scanActive) "STOP SCANNING" else "START SCAN",
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp,
                    letterSpacing = 2.sp
                )
            }

            // Scanner module grid
            Text(
                "SCANNERS",
                color = OnSurfaceMuted,
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                letterSpacing = 3.sp
            )

            ScannerGrid(
                state = state,
                onNavigate = onNavigate
            )
        }
    }
}

@Composable
private fun StatusRow(label: String, count: Int, color: Color) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Box(modifier = Modifier.size(8.dp).clip(CircleShape).background(color))
        Text(label, color = OnSurfaceMuted, fontSize = 12.sp, fontFamily = FontFamily.Monospace,
            modifier = Modifier.width(48.dp))
        Text(count.toString(), color = color, fontSize = 14.sp,
            fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun SdrStatusBadge(connected: Boolean, deviceName: String) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        color = if (connected) Color(0xFF0D2010) else SurfaceVariantDark,
        border = BorderStroke(1.dp, if (connected) RadarGreen.copy(0.5f) else Color(0xFF374151))
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Icon(
                Icons.Default.Usb,
                "SDR",
                tint = if (connected) RadarGreen else OnSurfaceMuted,
                modifier = Modifier.size(20.dp)
            )
            Column {
                Text(
                    if (connected) "RTL-SDR DONGLE CONNECTED" else "RTL-SDR NOT CONNECTED",
                    color = if (connected) RadarGreen else OnSurfaceMuted,
                    fontSize = 11.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 1.sp
                )
                if (connected && deviceName.isNotEmpty()) {
                    Text(deviceName, color = OnSurfaceMuted, fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace)
                } else if (!connected) {
                    Text("Plug in RTL4 dongle via USB-C OTG for SDR scanning",
                        color = OnSurfaceMuted.copy(0.6f), fontSize = 10.sp)
                }
            }
        }
    }
}

@Composable
private fun ScannerGrid(state: AppState, onNavigate: (Screen) -> Unit) {
    val summary = state.summary
    val items = listOf(
        ScannerTile("WiFi", Icons.Default.Wifi, Screen.Wifi, summary.wifiCount,
            state.wifiScanActive, RadarGreen),
        ScannerTile("Bluetooth", Icons.Default.Bluetooth, Screen.Bluetooth,
            summary.bluetoothCount + summary.bleCount, state.btScanActive || state.bleScanActive, TacticalBlue),
        ScannerTile("NFC", Icons.Default.Nfc, Screen.Nfc,
            if (state.lastNfcTag != null) 1 else 0, false, Color(0xFFEC4899)),
        ScannerTile("Cellular", Icons.Default.CellTower, Screen.Cellular,
            summary.cellCount, state.cellScanActive, WarningOrange),
        ScannerTile("SDR Radio", Icons.Default.Radio, Screen.Sdr,
            summary.sdrCount, state.sdrScanActive, Color(0xFF8B5CF6)),
        ScannerTile("Alerts", Icons.Default.Warning, Screen.Alerts,
            summary.alertCount + summary.suspiciousCount, false, AlertRed)
    )

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        items.chunked(2).forEach { row ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                row.forEach { tile ->
                    ScannerCard(
                        tile = tile,
                        modifier = Modifier.weight(1f),
                        onClick = { onNavigate(tile.screen) }
                    )
                }
                if (row.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

data class ScannerTile(
    val label: String,
    val icon: ImageVector,
    val screen: Screen,
    val count: Int,
    val active: Boolean,
    val color: Color
)

@Composable
private fun ScannerCard(
    tile: ScannerTile,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    val pulseTransition = rememberInfiniteTransition(label = "pulse_${tile.label}")
    val pulseAlpha by pulseTransition.animateFloat(
        initialValue = 0.3f, targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(800), repeatMode = RepeatMode.Reverse
        ),
        label = "alpha"
    )

    Surface(
        modifier = modifier
            .height(100.dp)
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
        color = SurfaceDark,
        border = BorderStroke(
            1.dp,
            if (tile.active) tile.color.copy(alpha = pulseAlpha) else Color(0xFF374151)
        )
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.SpaceBetween
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(tile.icon, tile.label, tint = tile.color, modifier = Modifier.size(22.dp))
                if (tile.active) {
                    Box(modifier = Modifier.size(8.dp).clip(CircleShape)
                        .background(tile.color.copy(alpha = pulseAlpha)))
                }
            }
            Column {
                Text(
                    tile.count.toString(),
                    color = tile.color,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                    fontFamily = FontFamily.Monospace
                )
                Text(
                    tile.label.uppercase(),
                    color = OnSurfaceMuted,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    letterSpacing = 1.sp
                )
            }
        }
    }
}
