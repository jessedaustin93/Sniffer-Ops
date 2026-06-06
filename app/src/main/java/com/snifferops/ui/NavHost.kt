package com.snifferops.ui

import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.snifferops.model.ThreatLevel
import com.snifferops.ui.screen.*
import com.snifferops.viewmodel.AppState
import com.snifferops.viewmodel.DashboardViewModel

sealed class Screen(val route: String) {
    object Dashboard : Screen("dashboard")
    object Wifi : Screen("wifi")
    object Bluetooth : Screen("bluetooth")
    object Nfc : Screen("nfc")
    object Cellular : Screen("cellular")
    object Sdr : Screen("sdr")
    object Alerts : Screen("alerts")
}

@Composable
fun SnifferOpsNavHost(
    state: AppState,
    viewModel: DashboardViewModel
) {
    val navController = rememberNavController()

    NavHost(
        navController = navController,
        startDestination = Screen.Dashboard.route
    ) {
        composable(Screen.Dashboard.route) {
            DashboardScreen(
                state = state,
                onNavigate = { navController.navigate(it.route) },
                onStartScan = { viewModel.startAllScans() },
                onStopScan = { viewModel.stopAllScans() },
                onClearData = { viewModel.clearAllData() }
            )
        }
        composable(Screen.Wifi.route) {
            WifiScreen(
                devices = state.wifiDevices,
                scanning = state.wifiScanActive,
                onStartScan = { viewModel.startWifiScan() },
                onStopScan = { viewModel.stopWifiScan() },
                onTriggerScan = { viewModel.triggerWifiScan() },
                onBack = { navController.popBackStack() }
            )
        }
        composable(Screen.Bluetooth.route) {
            BluetoothScreen(
                classicDevices = state.bluetoothDevices,
                bleDevices = state.bleDevices,
                scanningClassic = state.btScanActive,
                scanningBle = state.bleScanActive,
                onStartClassic = { viewModel.startBluetoothScan() },
                onStopClassic = { viewModel.stopBluetoothScan() },
                onStartBle = { viewModel.startBleScan() },
                onStopBle = { viewModel.stopBleScan() },
                onBack = { navController.popBackStack() }
            )
        }
        composable(Screen.Nfc.route) {
            NfcScreen(
                lastTag = state.lastNfcTag,
                onClear = { viewModel.clearNfcTag() },
                onBack = { navController.popBackStack() }
            )
        }
        composable(Screen.Cellular.route) {
            CellularScreen(
                towers = state.cellTowers,
                scanning = state.cellScanActive,
                onStartScan = { viewModel.startCellularScan() },
                onStopScan = { viewModel.stopCellularScan() },
                onBack = { navController.popBackStack() }
            )
        }
        composable(Screen.Sdr.route) {
            SdrScreen(
                signals = state.sdrSignals,
                connected = state.sdrConnected,
                hasPermission = state.sdrPermissionGranted,
                networkConnected = state.networkSdrConnected,
                networkHost = state.networkSdrHost,
                networkPort = state.networkSdrPort,
                awarenessSyncHost = state.awarenessSyncHost,
                awarenessSyncPort = state.awarenessSyncPort,
                awarenessSyncEnabled = state.awarenessSyncEnabled,
                awarenessSyncConnected = state.awarenessSyncConnected,
                awarenessSyncStatus = state.awarenessSyncStatus,
                awarenessSignalCount = state.awarenessSignalCount,
                deviceName = state.sdrDeviceName,
                scanning = state.sdrScanActive,
                onStartScan = { viewModel.startSdrScan() },
                onStopScan = { viewModel.stopSdrScan() },
                onNetworkEndpointChange = { host, port -> viewModel.setNetworkSdrEndpoint(host, port) },
                onConnectNetwork = { viewModel.connectNetworkSdr() },
                onDisconnectNetwork = { viewModel.disconnectNetworkSdr() },
                onAwarenessEndpointChange = { host, port -> viewModel.setAwarenessSyncEndpoint(host, port) },
                onAwarenessSyncEnabledChange = { viewModel.setAwarenessSyncEnabled(it) },
                onBack = { navController.popBackStack() }
            )
        }
        composable(Screen.Alerts.route) {
            AlertsScreen(
                wifiAlerts = state.wifiDevices.filter { it.threatLevel != ThreatLevel.SAFE },
                btAlerts = (state.bluetoothDevices + state.bleDevices + state.awarenessDevices).filter { it.threatLevel != ThreatLevel.SAFE },
                onBack = { navController.popBackStack() }
            )
        }
    }
}
