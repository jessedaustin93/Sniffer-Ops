package com.ethrox.detect.ui

import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.ethrox.detect.ui.screen.*
import com.ethrox.detect.viewmodel.AppState
import com.ethrox.detect.viewmodel.DashboardViewModel

sealed class Screen(val route: String) {
    object Dashboard : Screen("dashboard")
    object Wifi : Screen("wifi")
    object Bluetooth : Screen("bluetooth")
    object Nfc : Screen("nfc")
    object Cellular : Screen("cellular")
    object Sync : Screen("sync")
    object Alerts : Screen("alerts")
}

@Composable
fun EthroxDetectNavHost(
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
        composable(Screen.Sync.route) {
            SyncScreen(
                host = state.awarenessSyncHost,
                port = state.awarenessSyncPort,
                connected = state.awarenessSyncConnected,
                syncing = state.awarenessSyncInProgress,
                status = state.awarenessSyncStatus,
                compactionReadyCount = state.awarenessCompactionReadyCount,
                knownSignalCount = state.awarenessSignalCount,
                onAwarenessEndpointChange = { host, port -> viewModel.setAwarenessSyncEndpoint(host, port) },
                onConnectAwarenessSync = { viewModel.connectAwarenessSyncServer() },
                onSyncAwarenessNow = { viewModel.syncSavedAwarenessToHub() },
                onCompactAwareness = { viewModel.compactConfirmedPhoneHistory() },
                onBack = { navController.popBackStack() }
            )
        }
        composable(Screen.Alerts.route) {
            AlertsScreen(
                wifiAlerts = state.alertDevices.filter { it.signalType.name == "WIFI" },
                btAlerts = state.alertDevices.filter { it.signalType.name != "WIFI" },
                onBack = { navController.popBackStack() }
            )
        }
    }
}
