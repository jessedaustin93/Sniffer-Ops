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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.snifferops.model.SignalDevice
import com.snifferops.util.SignalDeviceGroup
import com.snifferops.util.groupSignalDevices
import com.snifferops.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertsScreen(
    wifiAlerts: List<SignalDevice>,
    btAlerts: List<SignalDevice>,
    onBack: () -> Unit
) {
    val allAlerts = (wifiAlerts + btAlerts).sortedByDescending { it.threatLevel.ordinal }
    val groupedAlerts = allAlerts.groupSignalDevices()
    var selectedGroup by remember { mutableStateOf<SignalDeviceGroup?>(null) }

    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text("SIGNAL ALERTS (${allAlerts.size})", fontFamily = FontFamily.Monospace,
                        color = AlertRed, letterSpacing = 1.sp, fontSize = 16.sp)
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
        if (allAlerts.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize().padding(padding).background(BackgroundDark),
                contentAlignment = Alignment.Center
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Icon(Icons.Default.CheckCircle, "Clear", tint = SafeGreen,
                        modifier = Modifier.size(64.dp))
                    Text("ALL CLEAR", color = SafeGreen, fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold, fontSize = 20.sp, letterSpacing = 4.sp)
                    Text("No alerts noticed", color = OnSurfaceMuted, fontSize = 14.sp)
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding).background(BackgroundDark),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(groupedAlerts, key = { it.key }) { group ->
                    AlertDeviceCard(group, onClick = { selectedGroup = group })
                }
            }
        }
    }

    selectedGroup?.let { group ->
        SignalDetailDialog(
            title = group.title,
            subtitle = group.typeLabel,
            rows = group.detailRows(),
            onDismiss = { selectedGroup = null }
        )
    }
}

@Composable
private fun AlertDeviceCard(group: SignalDeviceGroup, onClick: () -> Unit) {
    val device = group.primary
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
            Icon(Icons.Default.Warning, "Alert",
                tint = device.threatLevel.toColor(), modifier = Modifier.size(28.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(device.name, color = OnSurface, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                    if (group.count > 1) {
                        Text("${group.count} signals", color = device.threatLevel.toColor(), fontSize = 11.sp)
                    }
                    ThreatBadge(level = device.threatLevel)
                }
                Text(device.address, color = OnSurfaceMuted, fontSize = 11.sp,
                    fontFamily = FontFamily.Monospace)
                Text(device.deviceClass, color = device.threatLevel.toColor(), fontSize = 12.sp,
                    fontWeight = FontWeight.Medium)
                if (device.manufacturer.isNotEmpty() && device.manufacturer != "Unknown") {
                    Text("Mfr: ${device.manufacturer}", color = OnSurfaceMuted, fontSize = 11.sp)
                }
                Text("${device.signalStrength} dBm  |  ${device.signalType.name}",
                    color = OnSurfaceMuted, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
            }
        }
    }
}
