package com.snifferops.wear

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.material.*

val WatchGreen = Color(0xFF00FF41)
val WatchBlue = Color(0xFF0D84FF)
val WatchRed = Color(0xFFFF3131)
val WatchOrange = Color(0xFFFF8C00)
val WatchBg = Color(0xFF0A0E1A)
val WatchSurface = Color(0xFF111827)

class WearMainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                WearApp()
            }
        }
    }
}

@Composable
fun WearApp() {
    val state by WearStateHolder.state.collectAsStateWithLifecycle()

    Box(
        modifier = Modifier.fillMaxSize().background(WatchBg),
        contentAlignment = Alignment.Center
    ) {
        ScalingLazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            item {
                Text(
                    "SNIFFER OPS",
                    color = WatchGreen,
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 2.sp
                )
            }

            item {
                // Scanning status indicator
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Box(
                        modifier = Modifier.size(8.dp).clip(CircleShape)
                            .background(if (state.scanning) WatchGreen else Color.Gray)
                    )
                    Text(
                        if (state.scanning) "SCANNING" else "IDLE",
                        color = if (state.scanning) WatchGreen else Color.Gray,
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }
            }

            item {
                // Stats grid
                Column(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        WearStatChip("WiFi", state.wifiCount, WatchGreen,
                            modifier = Modifier.weight(1f))
                        WearStatChip("BT", state.btCount, WatchBlue,
                            modifier = Modifier.weight(1f))
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        WearStatChip("CELL", state.cellCount, WatchOrange,
                            modifier = Modifier.weight(1f))
                        WearStatChip("SDR", state.sdrCount, Color(0xFF8B5CF6),
                            modifier = Modifier.weight(1f))
                    }
                }
            }

            if (state.alertCount > 0) {
                item {
                    Surface(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp),
                        shape = RoundedCornerShape(8.dp),
                        backgroundColor = WatchRed.copy(alpha = 0.15f)
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center
                        ) {
                            Text("⚠ ${state.alertCount} ALERT${if (state.alertCount > 1) "S" else ""}",
                                color = WatchRed, fontSize = 12.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }

            item {
                // SDR dongle status
                Text(
                    if (state.sdrConnected) "SDR: CONNECTED" else "SDR: —",
                    color = if (state.sdrConnected) WatchGreen else Color.Gray,
                    fontSize = 10.sp, fontFamily = FontFamily.Monospace
                )
            }
        }
    }
}

@Composable
fun WearStatChip(
    label: String,
    count: Int,
    color: Color,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(8.dp),
        backgroundColor = WatchSurface
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(count.toString(), color = color, fontSize = 16.sp,
                fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            Text(label, color = Color.Gray, fontSize = 9.sp,
                fontFamily = FontFamily.Monospace)
        }
    }
}
