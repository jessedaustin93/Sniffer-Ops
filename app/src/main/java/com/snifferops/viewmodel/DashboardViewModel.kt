package com.snifferops.viewmodel

import android.app.Application
import android.content.Context
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.snifferops.data.AppDatabase
import com.snifferops.model.*
import com.snifferops.scanner.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

data class AppState(
    val wifiDevices: List<SignalDevice> = emptyList(),
    val bluetoothDevices: List<SignalDevice> = emptyList(),
    val bleDevices: List<SignalDevice> = emptyList(),
    val cellTowers: List<CellTower> = emptyList(),
    val sdrSignals: List<SdrSignal> = emptyList(),
    val lastNfcTag: NfcTag? = null,
    val sdrConnected: Boolean = false,
    val sdrPermissionGranted: Boolean = false,
    val sdrDeviceName: String = "",
    val networkSdrHost: String = "",
    val networkSdrPort: String = "1234",
    val networkSdrConnected: Boolean = false,
    val scanActive: Boolean = false,
    val wifiScanActive: Boolean = false,
    val btScanActive: Boolean = false,
    val bleScanActive: Boolean = false,
    val cellScanActive: Boolean = false,
    val sdrScanActive: Boolean = false,
    val alertCount: Int = 0,
    val errorMessage: String? = null
) {
    val summary: ScanSummary get() = ScanSummary(
        wifiCount = wifiDevices.size,
        bluetoothCount = bluetoothDevices.size,
        bleCount = bleDevices.size,
        nfcCount = if (lastNfcTag != null) 1 else 0,
        cellCount = cellTowers.size,
        sdrCount = sdrSignals.size,
        suspiciousCount = (wifiDevices + bluetoothDevices + bleDevices)
            .count { it.threatLevel == ThreatLevel.SUSPICIOUS },
        alertCount = (wifiDevices + bluetoothDevices + bleDevices)
            .count { it.threatLevel == ThreatLevel.ALERT },
        sdrConnected = sdrConnected || networkSdrConnected,
        scanActive = scanActive
    )
}

@OptIn(FlowPreview::class)
class DashboardViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        private const val TAG = "SnifferOpsWearSync"
    }

    private val db = AppDatabase.getInstance(application)
    private val wearDataClient = Wearable.getDataClient(application)
    private val wifiScanner = WifiScanner(application)
    private val btScanner = BluetoothScanner(application)
    private val cellularScanner = CellularScanner(application)
    val sdrScanner = RtlSdrScanner(application)
    private val networkSdrScanner = NetworkRtlSdrScanner()

    private val _state = MutableStateFlow(AppState())
    val state: StateFlow<AppState> = _state.asStateFlow()

    private var wifiJob: Job? = null
    private var btJob: Job? = null
    private var bleJob: Job? = null
    private var cellJob: Job? = null
    private var sdrJob: Job? = null
    private var sdrCheckJob: Job? = null

    init {
        checkSdrConnection()
        startSdrConnectionMonitor()
        startWearSync()
    }

    fun startAllScans() {
        startWifiScan()
        startBluetoothScan()
        startBleScan()
        startCellularScan()
        if (_state.value.sdrConnected) startSdrScan()
        _state.update { it.copy(scanActive = true) }
    }

    fun stopAllScans() {
        wifiJob?.cancel(); wifiJob = null
        btJob?.cancel(); btJob = null
        bleJob?.cancel(); bleJob = null
        cellJob?.cancel(); cellJob = null
        sdrJob?.cancel(); sdrJob = null
        _state.update { it.copy(
            scanActive = false,
            wifiScanActive = false,
            btScanActive = false,
            bleScanActive = false,
            cellScanActive = false,
            sdrScanActive = false
        ) }
    }

    fun startWifiScan() {
        wifiJob?.cancel()
        _state.update { it.copy(wifiScanActive = true) }
        wifiJob = viewModelScope.launch {
            wifiScanner.scan().collect { devices ->
                _state.update { s ->
                    s.copy(wifiDevices = devices, alertCount = s.summary.alertCount)
                }
                db.signalDeviceDao().insertAll(devices)
            }
        }
    }

    fun stopWifiScan() {
        wifiJob?.cancel(); wifiJob = null
        _state.update { it.copy(wifiScanActive = false) }
    }

    fun triggerWifiScan() {
        wifiScanner.triggerScan()
    }

    fun startBluetoothScan() {
        btJob?.cancel()
        _state.update { it.copy(btScanActive = true) }
        btJob = viewModelScope.launch {
            btScanner.scanClassic().collect { devices ->
                _state.update { it.copy(bluetoothDevices = devices) }
            }
        }
    }

    fun stopBluetoothScan() {
        btJob?.cancel(); btJob = null
        _state.update { it.copy(btScanActive = false) }
    }

    fun startBleScan() {
        bleJob?.cancel()
        _state.update { it.copy(bleScanActive = true) }
        bleJob = viewModelScope.launch {
            btScanner.scanBle().collect { devices ->
                _state.update { it.copy(bleDevices = devices) }
            }
        }
    }

    fun stopBleScan() {
        bleJob?.cancel(); bleJob = null
        _state.update { it.copy(bleScanActive = false) }
    }

    fun startCellularScan() {
        cellJob?.cancel()
        _state.update { it.copy(cellScanActive = true) }
        cellJob = viewModelScope.launch {
            cellularScanner.scan().collect { towers ->
                _state.update { it.copy(cellTowers = towers) }
            }
        }
    }

    fun stopCellularScan() {
        cellJob?.cancel(); cellJob = null
        _state.update { it.copy(cellScanActive = false) }
    }

    fun startSdrScan(centerFreq: Long = 100_000_000L) {
        val current = _state.value
        if (current.networkSdrConnected) {
            startNetworkSdrScan()
            return
        }
        if (!current.sdrConnected) return
        if (!sdrScanner.hasPermission()) {
            sdrScanner.requestPermission()
            checkSdrConnection()
            return
        }
        sdrJob?.cancel()
        _state.update { it.copy(sdrScanActive = true) }
        sdrJob = viewModelScope.launch {
            sdrScanner.sweepFrequencies().collect { signals ->
                _state.update { it.copy(sdrSignals = signals) }
            }
        }
    }

    fun stopSdrScan() {
        sdrJob?.cancel(); sdrJob = null
        _state.update { it.copy(sdrScanActive = false) }
    }

    fun onNfcTagDetected(tag: com.snifferops.model.NfcTag) {
        _state.update { it.copy(lastNfcTag = tag) }
    }

    fun clearNfcTag() {
        _state.update { it.copy(lastNfcTag = null) }
    }

    fun clearAllData() {
        viewModelScope.launch {
            db.signalDeviceDao().deleteAll()
            _state.update {
                AppState(
                    sdrConnected = it.sdrConnected,
                    sdrPermissionGranted = it.sdrPermissionGranted,
                    sdrDeviceName = it.sdrDeviceName
                )
            }
        }
    }

    fun onUsbDeviceAttached(device: UsbDevice) {
        sdrScanner.requestPermission()
        checkSdrConnection()
    }

    fun onUsbDeviceDetached(device: UsbDevice) {
        stopSdrScan()
        _state.update { it.copy(sdrConnected = false, sdrPermissionGranted = false, sdrDeviceName = "") }
    }

    fun onUsbPermissionResult() {
        checkSdrConnection()
        if (_state.value.scanActive && _state.value.sdrPermissionGranted) {
            startSdrScan()
        }
    }

    private fun startNetworkSdrScan() {
        val current = _state.value
        val port = current.networkSdrPort.toIntOrNull() ?: 1234
        sdrJob?.cancel()
        _state.update { it.copy(sdrScanActive = true) }
        sdrJob = viewModelScope.launch {
            runCatching {
                networkSdrScanner.sweepFrequencies(current.networkSdrHost, port).collect { signals ->
                    _state.update { it.copy(sdrSignals = signals, networkSdrConnected = true) }
                }
            }.onFailure { error ->
                _state.update {
                    it.copy(
                        sdrScanActive = false,
                        networkSdrConnected = false,
                        errorMessage = "Network SDR failed: ${error.message ?: "connection error"}"
                    )
                }
            }
        }
    }

    fun requestSdrPermissionIfConnected() {
        if (sdrScanner.isConnected() && !sdrScanner.hasPermission()) {
            sdrScanner.requestPermission()
        }
        checkSdrConnection()
    }

    fun setNetworkSdrEndpoint(host: String, port: String) {
        _state.update { it.copy(networkSdrHost = host, networkSdrPort = port) }
    }

    fun connectNetworkSdr() {
        val current = _state.value
        val port = current.networkSdrPort.toIntOrNull() ?: 1234
        if (current.networkSdrHost.isBlank()) {
            _state.update { it.copy(errorMessage = "Enter the Windows machine IP address for Network SDR") }
            return
        }

        _state.update {
            it.copy(
                networkSdrConnected = true,
                sdrDeviceName = "rtl_tcp ${current.networkSdrHost}:$port",
                errorMessage = null
            )
        }
    }

    fun disconnectNetworkSdr() {
        stopSdrScan()
        _state.update { it.copy(networkSdrConnected = false) }
    }

    private fun checkSdrConnection() {
        val connected = sdrScanner.isConnected()
        val hasPermission = connected && sdrScanner.hasPermission()
        _state.update { it.copy(
            sdrConnected = connected,
            sdrPermissionGranted = hasPermission,
            sdrDeviceName = when {
                it.networkSdrConnected -> it.sdrDeviceName
                connected -> sdrScanner.getDeviceName()
                else -> ""
            }
        ) }
    }

    private fun startSdrConnectionMonitor() {
        sdrCheckJob = viewModelScope.launch {
            while (true) {
                delay(3000)
                checkSdrConnection()
            }
        }
    }

    private fun startWearSync() {
        viewModelScope.launch {
            state
                .debounce(300)
                .distinctUntilChanged()
                .collect { syncWearState(it) }
        }
    }

    private fun syncWearState(appState: AppState) {
        val summary = appState.summary
        val request = PutDataMapRequest.create("/snifferops/summary").apply {
            dataMap.putInt("wifi", summary.wifiCount)
            dataMap.putInt("bt", summary.bluetoothCount + summary.bleCount)
            dataMap.putInt("cell", summary.cellCount)
            dataMap.putInt("sdr", summary.sdrCount)
            dataMap.putInt("alerts", summary.alertCount + summary.suspiciousCount)
            dataMap.putBoolean("scanning", summary.scanActive)
            dataMap.putBoolean("sdr_connected", summary.sdrConnected)
            dataMap.putLong("updated_at", System.currentTimeMillis())
            dataMap.putStringArrayList("wifi_items", appState.wifiDevices.toWearRows(8) { device ->
                wearRow(
                    title = device.name.ifBlank { "Hidden WiFi" },
                    detail = wearDetail(wearEstimatedType(device.deviceClass), device.address, "Ch ${device.channel}"),
                    value = "${device.signalStrength}"
                )
            })
            dataMap.putStringArrayList("bt_items", (appState.bluetoothDevices + appState.bleDevices).toWearRows(8) { device ->
                wearRow(
                    title = device.name.ifBlank { "Bluetooth" },
                    detail = wearDetail(wearEstimatedType(device.deviceClass), device.address),
                    value = "${device.signalStrength}"
                )
            })
            dataMap.putStringArrayList("cell_items", appState.cellTowers.toWearRows(8) { tower ->
                wearRow(
                    title = tower.carrier.ifBlank { tower.technology },
                    detail = wearDetail(wearEstimatedType("${tower.technology} cell tower"), "CID ${tower.cid}"),
                    value = "${tower.signalStrength}"
                )
            })
            dataMap.putStringArrayList("sdr_items", appState.sdrSignals.toWearRows(8) { signal ->
                wearRow(
                    title = signal.label.ifBlank { "RF SIGNAL" },
                    detail = wearDetail(wearEstimatedType(signal.label.ifBlank { "RF signal" }), signal.modulation),
                    value = formatWearFrequency(signal.frequency)
                )
            })
            dataMap.putStringArrayList("alert_items", appState.alertWearDevices().toWearRows(8) { device ->
                wearRow(
                    title = device.name.ifBlank { device.signalType.name },
                    detail = wearDetail(wearEstimatedType(device.deviceClass), device.threatLevel.name),
                    value = "${device.signalStrength}"
                )
            })
        }.asPutDataRequest().setUrgent()

        wearDataClient.putDataItem(request)
            .addOnSuccessListener {
                Log.d(
                    TAG,
                    "Published summary scanning=${summary.scanActive} wifi=${summary.wifiCount} " +
                        "bt=${summary.bluetoothCount + summary.bleCount} cell=${summary.cellCount} " +
                        "sdr=${summary.sdrCount} alerts=${summary.alertCount + summary.suspiciousCount}"
                )
            }
            .addOnFailureListener { error ->
                Log.w(TAG, "Failed to publish summary", error)
            }
    }

    private fun AppState.alertWearDevices(): List<SignalDevice> =
        (wifiDevices + bluetoothDevices + bleDevices)
            .filter { it.threatLevel == ThreatLevel.ALERT || it.threatLevel == ThreatLevel.SUSPICIOUS }
            .sortedByDescending { it.threatLevel.ordinal }

    private fun <T> List<T>.toWearRows(limit: Int, mapper: (T) -> String): ArrayList<String> =
        take(limit).mapTo(ArrayList(), mapper)

    private fun wearRow(title: String, detail: String, value: String): String =
        listOf(title, detail, value).joinToString("|") { it.cleanWearText() }

    private fun wearDetail(vararg parts: String): String =
        parts.filter { it.isNotBlank() && it != "Ch 0" }
            .joinToString("  ")

    private fun wearEstimatedType(type: String): String =
        type.takeIf { it.isNotBlank() }?.let { "$it*" } ?: ""

    private fun String.cleanWearText(): String =
        replace("|", "/").replace(Regex("\\s+"), " ").trim().take(32)

    private fun formatWearFrequency(hz: Long): String = when {
        hz >= 1_000_000_000L -> "${"%.2f".format(hz / 1_000_000_000.0)}G"
        hz >= 1_000_000L -> "${"%.1f".format(hz / 1_000_000.0)}M"
        hz >= 1_000L -> "${"%.0f".format(hz / 1_000.0)}K"
        else -> "$hz"
    }

    override fun onCleared() {
        super.onCleared()
        stopAllScans()
        sdrCheckJob?.cancel()
    }
}
