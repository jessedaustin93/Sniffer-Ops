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
import com.snifferops.model.CellTower
import com.snifferops.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CellularScreen(
    towers: List<CellTower>,
    scanning: Boolean,
    onStartScan: () -> Unit,
    onStopScan: () -> Unit,
    onBack: () -> Unit
) {
    var selectedTower by remember { mutableStateOf<CellTower?>(null) }

    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "CELLULAR SCANNER",
                        fontFamily = FontFamily.Monospace,
                        color = WarningOrange,
                        letterSpacing = 1.sp,
                        fontSize = 16.sp
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
        ) {
            ScanControlBar(
                scanning = scanning,
                count = towers.size,
                color = WarningOrange,
                onStart = onStartScan,
                onStop = onStopScan
            )

            if (towers.isEmpty()) {
                EmptyState("No cell towers detected", "Scan to detect nearby cellular towers")
            } else {
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(towers) { tower ->
                        CellTowerCard(tower, onClick = { selectedTower = tower })
                    }
                }
                EstimatedInfoFooter()
            }
        }
    }

    selectedTower?.let { tower ->
        SignalDetailDialog(
            title = tower.carrier.ifBlank { "${tower.technology} tower" },
            subtitle = "${tower.technology} cell tower",
            rows = tower.detailRows(),
            onDismiss = { selectedTower = null }
        )
    }
}

@Composable
private fun CellTowerCard(tower: CellTower, onClick: () -> Unit) {
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
            Icon(
                Icons.Default.CellTower, "Tower",
                tint = WarningOrange,
                modifier = Modifier.size(28.dp)
            )
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Surface(
                        shape = RoundedCornerShape(4.dp),
                        color = WarningOrange.copy(alpha = 0.15f)
                    ) {
                        Text(
                            tower.technology,
                            color = WarningOrange,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                            letterSpacing = 1.sp,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                        )
                    }
                    if (tower.carrier.isNotEmpty()) {
                        Text(tower.carrier, color = OnSurface, fontSize = 14.sp)
                    }
                }
                Text(
                    "Type*: ${tower.technology} cell tower",
                    color = WarningOrange, fontSize = 11.sp, fontFamily = FontFamily.Monospace
                )
                Text(
                    "CID: ${tower.cid}   LAC/TAC: ${tower.lac}",
                    color = OnSurfaceMuted, fontSize = 11.sp, fontFamily = FontFamily.Monospace
                )
                Text(
                    "MCC: ${tower.mcc}   MNC: ${tower.mnc}",
                    color = OnSurfaceMuted, fontSize = 11.sp, fontFamily = FontFamily.Monospace
                )
                Text(
                    "${tower.signalStrength} dBm",
                    color = signalColor(tower.signalStrength),
                    fontSize = 13.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

private fun signalColor(dbm: Int): Color = when {
    dbm >= -70 -> SafeGreen
    dbm >= -90 -> SuspiciousYellow
    else -> AlertRed
}
