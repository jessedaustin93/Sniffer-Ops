package com.snifferops.wear

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.Wearable
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.ScalingLazyColumn
import androidx.wear.compose.material.Text

val WatchGreen = Color(0xFF00FF41)
val WatchBlue = Color(0xFF0D84FF)
val WatchRed = Color(0xFFFF3131)
val WatchOrange = Color(0xFFFF8C00)
val WatchBg = Color(0xFF0A0E1A)
val WatchSurface = Color(0xFF111827)
private const val WearSyncTag = "SnifferOpsWearSync"

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
    val context = LocalContext.current
    val state by WearStateHolder.state.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) {
        Wearable.getDataClient(context).dataItems.addOnSuccessListener { items ->
            var foundSummary = false
            items.forEach { item ->
                if (item.uri.path == "/snifferops/summary") {
                    foundSummary = true
                    val dataMap = DataMapItem.fromDataItem(item).dataMap
                    Log.d(
                        WearSyncTag,
                        "Loaded cached summary scanning=${dataMap.getBoolean("scanning", false)} " +
                            "wifi=${dataMap.getInt("wifi", 0)} bt=${dataMap.getInt("bt", 0)} " +
                            "cell=${dataMap.getInt("cell", 0)} sdr=${dataMap.getInt("sdr", 0)} " +
                            "alerts=${dataMap.getInt("alerts", 0)}"
                    )
                    WearStateHolder.update(
                        wifi = dataMap.getInt("wifi", 0),
                        bt = dataMap.getInt("bt", 0),
                        cell = dataMap.getInt("cell", 0),
                        sdr = dataMap.getInt("sdr", 0),
                        alerts = dataMap.getInt("alerts", 0),
                        scanning = dataMap.getBoolean("scanning", false),
                        sdrConnected = dataMap.getBoolean("sdr_connected", false)
                    )
                }
            }
            if (!foundSummary) {
                Log.d(WearSyncTag, "No cached summary data item found")
            }
            items.release()
        }.addOnFailureListener { error ->
            Log.w(WearSyncTag, "Failed to load cached summary", error)
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(WatchBg),
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
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .clip(CircleShape)
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
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        WearStatChip("WiFi", state.wifiCount, WatchGreen, Modifier.weight(1f))
                        WearStatChip("BT", state.btCount, WatchBlue, Modifier.weight(1f))
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        WearStatChip("CELL", state.cellCount, WatchOrange, Modifier.weight(1f))
                        WearStatChip("SDR", state.sdrCount, Color(0xFF8B5CF6), Modifier.weight(1f))
                    }
                }
            }

            if (state.alertCount > 0) {
                item {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 4.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .background(WatchRed.copy(alpha = 0.15f))
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center
                        ) {
                            Text(
                                "! ${state.alertCount} ALERT${if (state.alertCount > 1) "S" else ""}",
                                color = WatchRed,
                                fontSize = 12.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }
            }

            item {
                Text(
                    if (state.sdrConnected) "SDR: CONNECTED" else "SDR: -",
                    color = if (state.sdrConnected) WatchGreen else Color.Gray,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace
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
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(WatchSurface)
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                count.toString(),
                color = color,
                fontSize = 16.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold
            )
            Text(
                label,
                color = Color.Gray,
                fontSize = 9.sp,
                fontFamily = FontFamily.Monospace
            )
        }
    }
}
