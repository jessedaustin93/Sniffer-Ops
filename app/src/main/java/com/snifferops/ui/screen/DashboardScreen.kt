package com.snifferops.ui.screen

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.CellTower
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Nfc
import androidx.compose.material.icons.filled.Radio
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.snifferops.R
import com.snifferops.ui.Screen
import com.snifferops.ui.theme.AlertRed
import com.snifferops.ui.theme.BackgroundDark
import com.snifferops.ui.theme.OnSurface
import com.snifferops.ui.theme.OnSurfaceMuted
import com.snifferops.ui.theme.RadarGreen
import com.snifferops.ui.theme.SnifferOpsCondensedFont
import com.snifferops.ui.theme.SnifferOpsFont
import com.snifferops.ui.theme.SnifferOpsTitleFont
import com.snifferops.ui.theme.SurfaceDark
import com.snifferops.ui.theme.TacticalBlue
import com.snifferops.ui.theme.WarningOrange
import com.snifferops.viewmodel.AppState
import com.snifferops.viewmodel.compactAwarenessProfiles
import com.snifferops.model.AwarenessProfile
import com.snifferops.model.AwarenessStatus
import com.snifferops.model.overview

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
    val alertTotal = state.alertTotal
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
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        Image(
                            painter = painterResource(R.drawable.snifferops_tile),
                            contentDescription = null,
                            modifier = Modifier.size(34.dp).clip(RoundedCornerShape(8.dp))
                        )
                        Column {
                            Text(
                                "SNIFFER OPS",
                                fontFamily = SnifferOpsTitleFont,
                                fontWeight = FontWeight.Bold,
                                color = RadarGreen,
                                fontSize = 20.sp,
                                letterSpacing = 3.sp
                            )
                            Text(
                                "SAMSUNG FIELD MONITOR",
                                color = OnSurfaceMuted,
                                fontSize = 10.sp,
                                fontFamily = SnifferOpsCondensedFont,
                                letterSpacing = 1.4.sp
                            )
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Black),
                actions = {
                    if (alertTotal > 0) {
                        BadgedBox(badge = {
                            Badge(containerColor = AlertRed) { Text("$alertTotal") }
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
                .background(
                    Brush.verticalGradient(
                        listOf(Color.Black, Color(0xFF020817), BackgroundDark)
                    )
                )
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = Color(0xB8050B12),
                shape = RoundedCornerShape(10.dp),
                border = BorderStroke(1.dp, Color(0xFF0B6B57))
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        RadarScope(
                            active = state.scanActive,
                            sweepAngle = sweepAngle,
                            modifier = Modifier.size(132.dp)
                        )
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            StatusRow("WIFI", summary.wifiCount, RadarGreen)
                            StatusRow("BT/BLE", summary.bluetoothCount + summary.bleCount, TacticalBlue)
                            StatusRow("CELL", summary.cellCount, WarningOrange)
                            StatusRow("SDR", summary.sdrCount, Color(0xFF8B5CF6))
                            StatusRow("ALERTS", alertTotal, AlertRed)
                        }
                    }
                    SignalMapStrip(profiles = state.compactAwarenessProfiles())
                }
            }

            SdrStatusBadge(
                connected = summary.sdrConnected,
                deviceName = state.sdrDeviceName,
                onConnectWindows = { onNavigate(Screen.Sdr) }
            )

            Button(
                onClick = if (state.scanActive) onStopScan else onStartScan,
                modifier = Modifier.fillMaxWidth().height(58.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (state.scanActive) AlertRed else Color(0xFF0D84FF),
                    contentColor = Color.White
                ),
                shape = RoundedCornerShape(6.dp),
                border = BorderStroke(1.dp, if (state.scanActive) Color(0xFFFF7A7A) else Color(0xFF22D3EE))
            ) {
                Icon(
                    if (state.scanActive) Icons.Default.Stop else Icons.Default.Search,
                    contentDescription = null,
                    modifier = Modifier.size(22.dp)
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    if (state.scanActive) "STOP SCAN" else "START SCAN",
                    fontFamily = SnifferOpsFont,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp,
                    letterSpacing = 2.sp
                )
            }

            Text(
                "SCANNERS",
                color = Color(0xFF22D3EE),
                fontSize = 11.sp,
                fontFamily = SnifferOpsCondensedFont,
                letterSpacing = 2.sp
            )

            ScannerGrid(state = state, onNavigate = onNavigate)
        }
    }
}

@Composable
private fun RadarScope(active: Boolean, sweepAngle: Float, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .clip(CircleShape)
            .background(Color(0xFF03120D))
            .border(2.dp, RadarGreen.copy(alpha = 0.85f), CircleShape),
        contentAlignment = Alignment.Center
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val center = Offset(size.width / 2f, size.height / 2f)
            drawCircle(RadarGreen.copy(alpha = 0.25f), radius = size.minDimension * 0.32f, center = center, style = androidx.compose.ui.graphics.drawscope.Stroke(1.4f))
            drawCircle(RadarGreen.copy(alpha = 0.18f), radius = size.minDimension * 0.20f, center = center, style = androidx.compose.ui.graphics.drawscope.Stroke(1.2f))
            drawLine(RadarGreen.copy(alpha = 0.34f), Offset(center.x, 8f), Offset(center.x, size.height - 8f), strokeWidth = 1.4f)
            drawLine(RadarGreen.copy(alpha = 0.34f), Offset(8f, center.y), Offset(size.width - 8f, center.y), strokeWidth = 1.4f)
            drawCircle(RadarGreen, radius = 4.5f, center = center)
        }
        if (active) {
            Box(Modifier.matchParentSize().rotate(sweepAngle)) {
                Box(
                    modifier = Modifier
                        .width(3.dp)
                        .height(62.dp)
                        .align(Alignment.TopCenter)
                        .background(
                            Brush.verticalGradient(
                                listOf(RadarGreen.copy(alpha = 0.9f), Color.Transparent)
                            )
                        )
                )
            }
        }
        Text(
            if (active) "LIVE" else "IDLE",
            color = if (active) RadarGreen else OnSurfaceMuted,
            fontSize = 13.sp,
            fontFamily = SnifferOpsFont,
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
private fun SignalMapStrip(profiles: List<AwarenessProfile>) {
    var expanded by remember { mutableStateOf(false) }
    val overview = profiles.overview()
    val important = profiles
        .filter { it.status != AwarenessStatus.NORMAL }
        .take(4)
        .ifEmpty { profiles.take(4) }

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .height(if (expanded) 206.dp else 86.dp)
            .clickable { expanded = !expanded },
        color = Color(0x66111827),
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(1.dp, Color(0xFF164E3A))
    ) {
        Column(
            modifier = Modifier.fillMaxSize().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                MiniAwarenessMap(profiles = profiles, modifier = Modifier.size(62.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "AWARENESS TIMELINE",
                        color = Color(0xFF22D3EE),
                        fontFamily = SnifferOpsCondensedFont,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp,
                        letterSpacing = 1.sp
                    )
                    Text(
                        "${overview.total} known / ${overview.scanSpots} spots",
                        color = OnSurface,
                        fontFamily = SnifferOpsCondensedFont,
                        fontWeight = FontWeight.Bold,
                        fontSize = 18.sp
                    )
                    Text(
                        "Normal ${overview.normal}  Watch ${overview.watch}  One-offs ${overview.oneOff}",
                        color = OnSurfaceMuted,
                        fontFamily = SnifferOpsCondensedFont,
                        fontSize = 10.sp
                    )
                }
            }
            if (expanded) {
                important.forEach { profile ->
                    AwarenessProfileLine(profile)
                }
            }
        }
    }
}

@Composable
private fun MiniAwarenessMap(profiles: List<AwarenessProfile>, modifier: Modifier = Modifier) {
    val gpsProfiles = profiles.filter { it.latitude != 0.0 || it.longitude != 0.0 }
    Canvas(modifier = modifier.clip(RoundedCornerShape(6.dp)).background(Color(0xFF0B1120))) {
        val grid = Color(0xFF143B46)
        drawLine(grid, Offset(size.width / 3f, 0f), Offset(size.width / 3f, size.height), strokeWidth = 1f)
        drawLine(grid, Offset(size.width * 2f / 3f, 0f), Offset(size.width * 2f / 3f, size.height), strokeWidth = 1f)
        drawLine(grid, Offset(0f, size.height / 2f), Offset(size.width, size.height / 2f), strokeWidth = 1f)
        if (gpsProfiles.isEmpty()) {
            drawCircle(RadarGreen.copy(alpha = 0.85f), radius = 7f, center = Offset(size.width / 2f, size.height / 2f))
            return@Canvas
        }

        val minLat = gpsProfiles.minOf { it.latitude }
        val maxLat = gpsProfiles.maxOf { it.latitude }.takeUnless { it == minLat } ?: (minLat + 0.001)
        val minLon = gpsProfiles.minOf { it.longitude }
        val maxLon = gpsProfiles.maxOf { it.longitude }.takeUnless { it == minLon } ?: (minLon + 0.001)
        gpsProfiles.takeLast(12).forEach { profile ->
            val x = 7f + (((profile.longitude - minLon) / (maxLon - minLon)).toFloat() * (size.width - 14f))
            val y = 7f + (((maxLat - profile.latitude) / (maxLat - minLat)).toFloat() * (size.height - 14f))
            val color = when (profile.status) {
                AwarenessStatus.NORMAL, AwarenessStatus.NOTICED -> RadarGreen
                AwarenessStatus.LEARNING -> TacticalBlue
                AwarenessStatus.ALERT -> AlertRed
                else -> WarningOrange
            }
            drawCircle(color, radius = 5f, center = Offset(x, y))
        }
    }
}

@Composable
private fun AwarenessProfileLine(profile: AwarenessProfile) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        val color = when (profile.status) {
            AwarenessStatus.NORMAL -> RadarGreen
            AwarenessStatus.LEARNING -> TacticalBlue
            AwarenessStatus.NOTICED -> RadarGreen
            AwarenessStatus.ONE_OFF -> WarningOrange
            AwarenessStatus.WATCH -> WarningOrange
            AwarenessStatus.ALERT -> AlertRed
        }
        Box(Modifier.size(7.dp).clip(CircleShape).background(color))
        Text(
            profile.name.take(18),
            color = OnSurface,
            fontFamily = SnifferOpsCondensedFont,
            fontSize = 10.sp,
            modifier = Modifier.width(112.dp)
        )
        Text(
            "${profile.status.label()}  ${profile.seenCount}x  ${profile.latestEvent.ifBlank { profile.deviceClass }}".take(58),
            color = OnSurfaceMuted,
            fontFamily = SnifferOpsCondensedFont,
            fontSize = 9.sp,
            modifier = Modifier.weight(1f)
        )
    }
}

private fun AwarenessStatus.label(): String = when (this) {
    AwarenessStatus.NORMAL -> "NORMAL"
    AwarenessStatus.LEARNING -> "LEARNING"
    AwarenessStatus.NOTICED -> "NOTICED"
    AwarenessStatus.ONE_OFF -> "ONE-OFF"
    AwarenessStatus.WATCH -> "WATCH"
    AwarenessStatus.ALERT -> "ALERT"
}

@Composable
private fun StatusRow(label: String, count: Int, color: Color) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(color))
        Text(label, color = OnSurfaceMuted, fontSize = 12.sp, fontFamily = SnifferOpsCondensedFont, modifier = Modifier.width(88.dp))
        Text(count.toString(), color = color, fontSize = 16.sp, fontFamily = SnifferOpsCondensedFont, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun SdrStatusBadge(connected: Boolean, deviceName: String, onConnectWindows: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        color = if (connected) Color(0xFF061D12) else SurfaceDark,
        border = BorderStroke(1.dp, if (connected) RadarGreen.copy(0.55f) else Color(0xFF255866))
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Image(
                painter = painterResource(R.drawable.snifferops_tile),
                contentDescription = null,
                modifier = Modifier.size(34.dp).clip(RoundedCornerShape(6.dp))
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    if (connected) "RTL-SDR LINK ONLINE" else "RTL-SDR LINK IDLE",
                    color = if (connected) RadarGreen else OnSurfaceMuted,
                    fontSize = 12.sp,
                    fontFamily = SnifferOpsFont,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 1.sp
                )
                Text(
                    if (connected && deviceName.isNotEmpty()) deviceName else "USB-C OTG or PC feed",
                    color = OnSurfaceMuted.copy(0.76f),
                    fontSize = 11.sp,
                    fontFamily = SnifferOpsCondensedFont
                )
            }
            Button(
                onClick = onConnectWindows,
                shape = RoundedCornerShape(6.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF8B5CF6))
            ) {
                Icon(Icons.Default.Radio, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(
                    "PC",
                    fontFamily = SnifferOpsCondensedFont,
                    fontWeight = FontWeight.Bold,
                    fontSize = 11.sp
                )
            }
        }
    }
}

@Composable
private fun ScannerGrid(state: AppState, onNavigate: (Screen) -> Unit) {
    val summary = state.summary
    val alertTotal = state.alertTotal
    val items = listOf(
        ScannerTile("WiFi", Icons.Default.Wifi, Screen.Wifi, summary.wifiCount, state.wifiScanActive, RadarGreen),
        ScannerTile("Bluetooth", Icons.Default.Bluetooth, Screen.Bluetooth, summary.bluetoothCount + summary.bleCount, state.btScanActive || state.bleScanActive, TacticalBlue),
        ScannerTile("NFC", Icons.Default.Nfc, Screen.Nfc, if (state.lastNfcTag != null) 1 else 0, false, Color(0xFFEC4899)),
        ScannerTile("Cellular", Icons.Default.CellTower, Screen.Cellular, summary.cellCount, state.cellScanActive, WarningOrange),
        ScannerTile("SDR Radio", Icons.Default.Radio, Screen.Sdr, summary.sdrCount, state.sdrScanActive, Color(0xFF8B5CF6)),
        ScannerTile("Alerts", Icons.Default.Warning, Screen.Alerts, alertTotal, false, AlertRed)
    )

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items.chunked(2).forEach { row ->
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { tile ->
                    ScannerCard(tile = tile, modifier = Modifier.weight(1f), onClick = { onNavigate(tile.screen) })
                }
            }
        }
    }
}

private data class ScannerTile(
    val label: String,
    val icon: ImageVector,
    val screen: Screen,
    val count: Int,
    val active: Boolean,
    val color: Color
)

@Composable
private fun ScannerCard(tile: ScannerTile, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val pulseTransition = rememberInfiniteTransition(label = "pulse_${tile.label}")
    val pulseAlpha by pulseTransition.animateFloat(
        initialValue = 0.25f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(animation = tween(900), repeatMode = RepeatMode.Reverse),
        label = "alpha"
    )

    Surface(
        modifier = modifier.height(94.dp).clickable(onClick = onClick),
        shape = RoundedCornerShape(8.dp),
        color = Color(0xCC111827),
        border = BorderStroke(1.dp, if (tile.active) tile.color.copy(alpha = pulseAlpha) else Color(0xFF255866))
    ) {
        Row(
            modifier = Modifier.fillMaxSize().padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Box(
                modifier = Modifier.size(44.dp).clip(RoundedCornerShape(7.dp)).border(1.dp, tile.color, RoundedCornerShape(7.dp)).background(tile.color.copy(0.08f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(tile.icon, tile.label, tint = tile.color, modifier = Modifier.size(25.dp))
            }
            Column(verticalArrangement = Arrangement.Center) {
                Text(tile.count.toString(), color = tile.color, fontSize = 23.sp, fontWeight = FontWeight.Bold, fontFamily = SnifferOpsCondensedFont)
                Text(tile.label.uppercase(), color = OnSurface, fontSize = 11.sp, fontFamily = SnifferOpsCondensedFont, letterSpacing = 1.sp)
                Text(tile.subtitle(), color = OnSurfaceMuted, fontSize = 9.sp, fontFamily = SnifferOpsCondensedFont)
            }
        }
    }
}

private fun ScannerTile.subtitle(): String = when (screen) {
    Screen.Dashboard -> "Command overview"
    Screen.Wifi -> "WLAN scan"
    Screen.Bluetooth -> "BT/BLE scan"
    Screen.Nfc -> "Samsung NFC reader"
    Screen.Cellular -> "Radio info"
    Screen.Sdr -> "Measured RF peaks"
    Screen.Alerts -> "App status"
}
