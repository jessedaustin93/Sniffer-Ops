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
fun BluetoothScreen(
    classicDevices: List<SignalDevice>,
    bleDevices: List<SignalDevice>,
    scanningClassic: Boolean,
    scanningBle: Boolean,
    onStartClassic: () -> Unit,
    onStopClassic: () -> Unit,
    onStartBle: () -> Unit,
    onStopBle: () -> Unit,
    onBack: () -> Unit
) {
    var selectedTab by remember { mutableIntStateOf(0) }
    var selectedGroup by remember { mutableStateOf<SignalDeviceGroup?>(null) }
    val tabs = listOf("Classic BT (${classicDevices.size})", "BLE (${bleDevices.size})")

    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text("BLUETOOTH SCANNER", fontFamily = FontFamily.Monospace,
                        color = TacticalBlue, letterSpacing = 1.sp, fontSize = 16.sp)
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
            TabRow(
                selectedTabIndex = selectedTab,
                containerColor = SurfaceDark,
                contentColor = TacticalBlue
            ) {
                tabs.forEachIndexed { index, title ->
                    Tab(
                        selected = selectedTab == index,
                        onClick = { selectedTab = index },
                        text = { Text(title, fontFamily = FontFamily.Monospace, fontSize = 12.sp) }
                    )
                }
            }

            when (selectedTab) {
                0 -> {
                    ScanControlBar(
                        scanning = scanningClassic, count = classicDevices.size,
                        color = TacticalBlue, onStart = onStartClassic, onStop = onStopClassic
                    )
                    BtDeviceList(
                        groups = classicDevices.groupSignalDevices(),
                        onSelect = { selectedGroup = it }
                    )
                }
                1 -> {
                    ScanControlBar(
                        scanning = scanningBle, count = bleDevices.size,
                        color = TacticalBlue, onStart = onStartBle, onStop = onStopBle
                    )
                    BtDeviceList(
                        groups = bleDevices.groupSignalDevices(),
                        onSelect = { selectedGroup = it }
                    )
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
private fun ColumnScope.BtDeviceList(groups: List<SignalDeviceGroup>, onSelect: (SignalDeviceGroup) -> Unit) {
    if (groups.isEmpty()) {
        EmptyState("No Bluetooth devices found", "Tap scan to search for nearby devices")
        return
    }
    LazyColumn(
        modifier = Modifier.weight(1f),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(groups, key = { it.key }) { group ->
            BtDeviceCard(group, onClick = { onSelect(group) })
        }
    }
    EstimatedInfoFooter()
}

@Composable
private fun BtDeviceCard(group: SignalDeviceGroup, onClick: () -> Unit) {
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
            Icon(
                Icons.Default.Bluetooth, "BT",
                tint = device.threatLevel.toColor(),
                modifier = Modifier.size(28.dp)
            )
            Column(modifier = Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(device.name, color = OnSurface, fontWeight = FontWeight.Medium, fontSize = 14.sp)
                    if (group.count > 1) {
                        Text("${group.count} signals", color = TacticalBlue, fontSize = 11.sp)
                    }
                    ThreatBadge(level = device.threatLevel)
                }
                Text(device.address, color = OnSurfaceMuted, fontSize = 11.sp,
                    fontFamily = FontFamily.Monospace)
                if (device.deviceClass.isNotEmpty()) {
                    Text("Type*: ${device.deviceClass}", color = TacticalBlue, fontSize = 11.sp)
                }
                Text("${device.signalStrength} dBm", color = OnSurfaceMuted,
                    fontSize = 11.sp, fontFamily = FontFamily.Monospace)
            }
        }
    }
}
