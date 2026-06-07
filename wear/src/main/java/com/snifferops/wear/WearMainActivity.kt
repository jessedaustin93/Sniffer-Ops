package com.snifferops.wear

import android.content.pm.ActivityInfo
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.ScalingLazyColumn
import androidx.wear.compose.material.Text
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.Wearable

val WatchGreen = Color(0xFF00FF41)
val WatchBlue = Color(0xFF0D84FF)
val WatchRed = Color(0xFFFF3131)
val WatchOrange = Color(0xFFFF8C00)
val WatchBg = Color(0xFF020617)
val WatchSurface = Color(0xFF111827)
private const val WearSyncTag = "SnifferOpsWearSync"
private val WatchFont = FontFamily(Font(R.font.spyagency3ital))
private val WatchCondensedFont = FontFamily(Font(R.font.spyagency3cond))
private val WatchTitleFont = FontFamily(Font(R.font.spyagency3gradital))

private enum class WatchPanel(val label: String) {
    Dashboard("WATCH MONITOR"),
    Wifi("WIFI"),
    Bluetooth("BT"),
    Cellular("CELL"),
    Sdr("SDR"),
    Awareness("AWARE"),
    Alerts("ALERTS")
}

class WearMainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        setContent {
            MaterialTheme {
                WearApp()
            }
        }
    }
}

@Composable
fun WearApp() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val state by WearStateHolder.state.collectAsStateWithLifecycle()
    var selectedPanel by remember { mutableStateOf(WatchPanel.Dashboard) }

    BackHandler(enabled = selectedPanel != WatchPanel.Dashboard) {
        selectedPanel = WatchPanel.Dashboard
    }

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
                        awareness = dataMap.getInt("awareness", 0),
                        scanning = dataMap.getBoolean("scanning", false),
                        sdrConnected = dataMap.getBoolean("sdr_connected", false),
                        wifiItems = dataMap.readItems("wifi_items"),
                        btItems = dataMap.readItems("bt_items"),
                        cellItems = dataMap.readItems("cell_items"),
                        sdrItems = dataMap.readItems("sdr_items"),
                        alertItems = dataMap.readItems("alert_items"),
                        awarenessItems = dataMap.readItems("awareness_items")
                    )
                }
            }
            if (!foundSummary) Log.d(WearSyncTag, "No cached summary data item found")
            items.release()
        }.addOnFailureListener { error ->
            Log.w(WearSyncTag, "Failed to load cached summary", error)
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(Color.Black, WatchBg))),
        contentAlignment = Alignment.Center
    ) {
        ScalingLazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(7.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            item {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Image(
                        painter = painterResource(R.drawable.snifferops_tile),
                        contentDescription = null,
                        modifier = Modifier.size(28.dp).clip(RoundedCornerShape(7.dp))
                    )
                    Column {
                        Text(
                            "SNIFFER OPS",
                            color = WatchGreen,
                            fontSize = 12.sp,
                            fontFamily = WatchTitleFont,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 1.5.sp
                        )
                        Text(
                            selectedPanel.label,
                            color = Color.Gray,
                            fontSize = 9.sp,
                            fontFamily = WatchCondensedFont
                        )
                    }
                }
            }

            if (selectedPanel == WatchPanel.Dashboard) {
                item {
                    WatchRadar(active = state.scanning)
                }

                item {
                    Column(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            WearStatChip("WiFi", state.wifiCount, WatchGreen, Modifier.weight(1f)) {
                                selectedPanel = WatchPanel.Wifi
                            }
                            WearStatChip("BT", state.btCount, WatchBlue, Modifier.weight(1f)) {
                                selectedPanel = WatchPanel.Bluetooth
                            }
                        }
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            WearStatChip("CELL", state.cellCount, WatchOrange, Modifier.weight(1f)) {
                                selectedPanel = WatchPanel.Cellular
                            }
                            WearStatChip("SDR", state.sdrCount, Color(0xFF8B5CF6), Modifier.weight(1f)) {
                                selectedPanel = WatchPanel.Sdr
                            }
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
                                .background(WatchRed.copy(alpha = 0.16f))
                                .border(1.dp, WatchRed.copy(alpha = 0.6f), RoundedCornerShape(8.dp))
                                .clickable { selectedPanel = WatchPanel.Alerts }
                        ) {
                            Text(
                                "! ${state.alertCount} ALERT${if (state.alertCount > 1) "S" else ""}",
                                color = WatchRed,
                                fontSize = 13.sp,
                                fontFamily = WatchFont,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.align(Alignment.Center).padding(vertical = 6.dp)
                            )
                        }
                    }
                }

                item {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 4.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .background(Color(0xFF22D3EE).copy(alpha = 0.12f))
                            .border(1.dp, Color(0xFF22D3EE).copy(alpha = 0.45f), RoundedCornerShape(8.dp))
                            .clickable { selectedPanel = WatchPanel.Awareness }
                    ) {
                        Column(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text(
                                "AWARENESS ${state.awarenessCount}",
                                color = Color(0xFF22D3EE),
                                fontSize = 12.sp,
                                fontFamily = WatchFont,
                                fontWeight = FontWeight.Bold
                            )
                            Text(
                                "timeline / normal / one-offs",
                                color = Color.Gray,
                                fontSize = 8.sp,
                                fontFamily = WatchCondensedFont
                            )
                        }
                    }
                }

                item {
                    Text(
                        if (state.sdrConnected) "SDR: CONNECTED" else "SDR: STANDBY",
                        color = if (state.sdrConnected) WatchGreen else Color.Gray,
                        fontSize = 11.sp,
                        fontFamily = WatchCondensedFont
                    )
                }
            } else {
                item {
                    WearSignalList(
                        title = selectedPanel.label,
                        items = state.itemsFor(selectedPanel),
                        color = selectedPanel.color(),
                        onBack = { selectedPanel = WatchPanel.Dashboard }
                    )
                }
            }
        }
    }
}

@Composable
private fun WatchRadar(active: Boolean) {
    Box(
        modifier = Modifier
            .size(72.dp)
            .clip(CircleShape)
            .background(Color(0xFF03120D))
            .border(1.dp, WatchGreen.copy(alpha = 0.8f), CircleShape),
        contentAlignment = Alignment.Center
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val center = Offset(size.width / 2f, size.height / 2f)
            drawCircle(WatchGreen.copy(alpha = 0.25f), radius = size.minDimension * 0.32f, center = center, style = androidx.compose.ui.graphics.drawscope.Stroke(1.1f))
            drawCircle(WatchGreen.copy(alpha = 0.18f), radius = size.minDimension * 0.20f, center = center, style = androidx.compose.ui.graphics.drawscope.Stroke(1f))
            drawLine(WatchGreen.copy(alpha = 0.32f), Offset(center.x, 5f), Offset(center.x, size.height - 5f), strokeWidth = 1f)
            drawLine(WatchGreen.copy(alpha = 0.32f), Offset(5f, center.y), Offset(size.width - 5f, center.y), strokeWidth = 1f)
            drawCircle(WatchGreen, radius = 3.3f, center = center)
        }
        Text(
            if (active) "LIVE" else "IDLE",
            color = if (active) WatchGreen else Color.Gray,
            fontSize = 11.sp,
            fontFamily = WatchFont,
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
fun WearStatChip(label: String, count: Int, color: Color, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(WatchSurface)
            .border(BorderStroke(1.dp, color.copy(alpha = 0.45f)), RoundedCornerShape(8.dp))
            .clickable(onClick = onClick)
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                count.toString(),
                color = color,
                fontSize = 18.sp,
                fontFamily = WatchCondensedFont,
                fontWeight = FontWeight.Bold
            )
            Text(
                label.uppercase(),
                color = Color.Gray,
                fontSize = 9.sp,
                fontFamily = WatchCondensedFont
            )
        }
    }
}

@Composable
private fun WearSignalList(
    title: String,
    items: List<WearSignalItem>,
    color: Color,
    onBack: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(color.copy(alpha = 0.14f))
                .border(BorderStroke(1.dp, color.copy(alpha = 0.55f)), RoundedCornerShape(8.dp))
                .clickable(onClick = onBack)
        ) {
            Text(
                "< $title (${items.size})",
                color = color,
                fontSize = 12.sp,
                fontFamily = WatchFont,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.align(Alignment.Center).padding(vertical = 7.dp)
            )
        }

        if (items.isEmpty()) {
            WearSignalRow(
                item = WearSignalItem("NO SIGNALS", "Waiting for phone scan data", "--"),
                color = Color.Gray
            )
        } else {
            items.forEach { item ->
                WearSignalRow(item = item, color = color)
            }
        }
    }
}

@Composable
private fun WearSignalRow(item: WearSignalItem, color: Color) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(WatchSurface)
            .border(BorderStroke(1.dp, color.copy(alpha = 0.35f)), RoundedCornerShape(8.dp))
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                Text(
                    item.title,
                    color = Color.White,
                    fontSize = 11.sp,
                    fontFamily = WatchCondensedFont,
                    maxLines = 1
                )
                Text(
                    item.detail,
                    color = Color.Gray,
                    fontSize = 9.sp,
                    fontFamily = WatchCondensedFont,
                    maxLines = 1
                )
            }
            Text(
                item.value,
                color = color,
                fontSize = 13.sp,
                fontFamily = WatchCondensedFont,
                fontWeight = FontWeight.Bold,
                maxLines = 1
            )
        }
    }
}

private fun WearState.itemsFor(panel: WatchPanel): List<WearSignalItem> = when (panel) {
    WatchPanel.Dashboard -> emptyList()
    WatchPanel.Wifi -> wifiItems
    WatchPanel.Bluetooth -> btItems
    WatchPanel.Cellular -> cellItems
    WatchPanel.Sdr -> sdrItems
    WatchPanel.Awareness -> awarenessItems
    WatchPanel.Alerts -> alertItems
}

private fun WatchPanel.color(): Color = when (this) {
    WatchPanel.Dashboard -> WatchGreen
    WatchPanel.Wifi -> WatchGreen
    WatchPanel.Bluetooth -> WatchBlue
    WatchPanel.Cellular -> WatchOrange
    WatchPanel.Sdr -> Color(0xFF8B5CF6)
    WatchPanel.Awareness -> Color(0xFF22D3EE)
    WatchPanel.Alerts -> WatchRed
}
