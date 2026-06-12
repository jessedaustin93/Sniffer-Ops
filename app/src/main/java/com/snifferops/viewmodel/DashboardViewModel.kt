package com.snifferops.viewmodel

import android.app.Application
import android.content.Context
import android.content.Intent
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.core.content.ContextCompat
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.snifferops.data.AppDatabase
import com.snifferops.data.SignalDetectionStore
import com.snifferops.model.*
import com.snifferops.scanner.*
import com.snifferops.service.ScannerService
import com.snifferops.sync.AwarenessSyncClient
import com.snifferops.util.groupSignalDevices
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import java.net.SocketTimeoutException

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
    val awarenessSyncHost: String = "",
    val awarenessSyncPort: String = "8765",
    val awarenessSyncEnabled: Boolean = false,
    val awarenessSyncConnected: Boolean = false,
    val awarenessSyncStatus: String = "Sync off",
    val awarenessSyncInProgress: Boolean = false,
    val awarenessCompactionReadyCount: Int = 0,
    val awarenessSignalCount: Int = 0,
    val awarenessDevices: List<SignalDevice> = emptyList(),
    val awarenessProfiles: List<AwarenessProfile> = emptyList(),
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
        noticedCount = alertDevices.count { it.threatLevel == ThreatLevel.UNKNOWN },
        suspiciousCount = alertDevices.count { it.threatLevel == ThreatLevel.SUSPICIOUS },
        alertCount = alertDevices.count { it.threatLevel == ThreatLevel.ALERT },
        sdrConnected = sdrConnected || networkSdrConnected,
        scanActive = scanActive
    )

    val alertTotal: Int get() = summary.alertCount + summary.suspiciousCount + summary.noticedCount
    val alertDevices: List<SignalDevice> get() =
        (wifiDevices + bluetoothDevices + bleDevices + awarenessDevices).filter { it.isAlertRelevant() }
}

@OptIn(FlowPreview::class)
class DashboardViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        private const val TAG = "SnifferOpsWearSync"
        private const val SERVER_PREFS = "snifferops_windows_server"
        private const val PREF_NETWORK_HOST = "network_sdr_host"
        private const val PREF_NETWORK_PORT = "network_sdr_port"
        private const val PREF_AWARENESS_HOST = "awareness_sync_host"
        private const val PREF_AWARENESS_PORT = "awareness_sync_port"
        private const val PREF_AWARENESS_ENABLED = "awareness_sync_enabled"
    }

    private val appContext = application.applicationContext
    private val serverPrefs = appContext.getSharedPreferences(SERVER_PREFS, Context.MODE_PRIVATE)
    private val db = AppDatabase.getInstance(application)
    private val wearDataClient = Wearable.getDataClient(application)
    private val wifiScanner = WifiScanner(application)
    private val btScanner = BluetoothScanner(application)
    private val cellularScanner = CellularScanner(application)
    val sdrScanner = RtlSdrScanner(application)
    private val networkSdrScanner = NetworkRtlSdrScanner()
    private val awarenessSyncClient = AwarenessSyncClient(application)
    private val detectionStore = SignalDetectionStore(application)

    private val _state = MutableStateFlow(AppState())
    val state: StateFlow<AppState> = _state.asStateFlow()

    private var wifiJob: Job? = null
    private var btJob: Job? = null
    private var bleJob: Job? = null
    private var cellJob: Job? = null
    private var sdrJob: Job? = null
    private var sdrCheckJob: Job? = null
    private var pcSdrScanJob: Job? = null

    init {
        restoreWindowsServerSettings()
        loadPersistedSignals()
        loadCompactionState()
        checkSdrConnection()
        startSdrConnectionMonitor()
        startWearSync()
        autoConnectWindowsServer()
    }

    fun startAllScans() {
        ContextCompat.startForegroundService(
            appContext,
            Intent(appContext, ScannerService::class.java).setAction(ScannerService.ACTION_START)
        )
        if (_state.value.sdrConnected) startSdrScan()
        _state.update {
            it.copy(
                scanActive = true,
                wifiScanActive = true,
                btScanActive = true,
                bleScanActive = true,
                cellScanActive = true
            )
        }
    }

    fun stopAllScans() {
        wifiJob?.cancel(); wifiJob = null
        btJob?.cancel(); btJob = null
        bleJob?.cancel(); bleJob = null
        cellJob?.cancel(); cellJob = null
        sdrJob?.cancel(); sdrJob = null
        appContext.startService(
            Intent(appContext, ScannerService::class.java).setAction(ScannerService.ACTION_STOP)
        )
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
                persistSignals(devices)
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
                persistSignals(devices)
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
                persistSignals(devices)
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
                persistSignals(towers.toCellSignalDevices())
            }
        }
    }

    fun stopCellularScan() {
        cellJob?.cancel(); cellJob = null
        _state.update { it.copy(cellScanActive = false) }
    }

    fun startSdrScan(centerFreq: Long = 100_000_000L) {
        val current = _state.value
        val windowsHost = current.awarenessSyncHost.ifBlank { current.networkSdrHost }
        if (windowsHost.isNotBlank()) {
            startWindowsSdrDeepScan(windowsHost, current.awarenessSyncPort.toIntOrNull() ?: 8765)
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
                persistSignals(signals.toSdrSignalDevices())
            }
        }
    }

    fun stopSdrScan() {
        sdrJob?.cancel(); sdrJob = null
        _state.update { it.copy(sdrScanActive = false) }
    }

    fun onNfcTagDetected(tag: com.snifferops.model.NfcTag) {
        viewModelScope.launch {
            persistSignals(listOf(tag.toSignalDevice()))
        }
    }

    fun clearNfcTag() {
        _state.update { it.copy(lastNfcTag = null) }
    }

    fun clearAllData() {
        viewModelScope.launch {
            db.signalDeviceDao().deleteAll()
            db.signalDeviceDao().deleteAllSightings()
            _state.update {
                val current = it
                AppState(
                    sdrConnected = it.sdrConnected,
                    sdrPermissionGranted = it.sdrPermissionGranted,
                    sdrDeviceName = it.sdrDeviceName,
                    networkSdrHost = current.networkSdrHost,
                    networkSdrPort = current.networkSdrPort,
                    networkSdrConnected = current.networkSdrConnected,
                    awarenessSyncHost = current.awarenessSyncHost,
                    awarenessSyncPort = current.awarenessSyncPort,
                    awarenessSyncEnabled = current.awarenessSyncEnabled,
                    awarenessSyncConnected = current.awarenessSyncConnected,
                    awarenessSyncStatus = current.awarenessSyncStatus,
                    awarenessSignalCount = current.awarenessSignalCount,
                    awarenessDevices = current.awarenessDevices,
                    awarenessProfiles = current.awarenessProfiles
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
                    persistSignals(signals.toSdrSignalDevices())
                    _state.update { it.copy(networkSdrConnected = true) }
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
        saveWindowsServerSettings()
    }

    private fun startWindowsSdrDeepScan(host: String, port: Int) {
        pcSdrScanJob?.cancel()
        _state.update {
            it.copy(
                sdrScanActive = true,
                awarenessSyncInProgress = true,
                awarenessSyncConnected = true,
                awarenessSyncStatus = "Starting PC deep SDR scan..."
            )
        }
        pcSdrScanJob = viewModelScope.launch {
            runCatching {
                awarenessSyncClient.runWindowsSdrDeepScan(host, port)
            }.onSuccess { initial ->
                if (initial.completed) {
                    applyPcSdrDeepScanResult(initial, host, port)
                    return@launch
                }

                _state.update {
                    it.copy(
                        sdrScanActive = true,
                        networkSdrConnected = true,
                        sdrDeviceName = "PC rtl_power $host:$port",
                        awarenessSyncConnected = true,
                        awarenessSyncInProgress = false,
                        awarenessSyncStatus = initial.message.ifBlank { "PC deep scan running..." }
                    )
                }

                var misses = 0
                while (isActive) {
                    delay(3_000)
                    val polled = runCatching { awarenessSyncClient.pollWindowsSdrDeepScan(host, port) }
                    polled.onSuccess { result ->
                        misses = 0
                        if (result.completed) {
                            applyPcSdrDeepScanResult(result, host, port)
                            return@launch
                        }
                        _state.update {
                            it.copy(
                                sdrScanActive = result.running,
                                awarenessSyncConnected = true,
                                awarenessSyncStatus = result.message.ifBlank { "PC deep scan running..." }
                            )
                        }
                    }.onFailure {
                        misses += 1
                        _state.update {
                            it.copy(
                                sdrScanActive = true,
                                awarenessSyncConnected = misses < 4,
                                awarenessSyncStatus = "PC is still busy with SDR scan..."
                            )
                        }
                        if (misses >= 20) throw it
                    }
                }
            }.onFailure { error ->
                _state.update {
                    it.copy(
                        sdrScanActive = false,
                        awarenessSyncConnected = false,
                        awarenessSyncInProgress = false,
                        awarenessSyncStatus = "PC SDR scan failed: ${error.message ?: "connection error"}",
                        errorMessage = "PC SDR scan failed: ${error.message ?: "connection error"}"
                    )
                }
            }
        }
    }

    private suspend fun applyPcSdrDeepScanResult(
        result: com.snifferops.sync.WindowsSdrDeepScanResult,
        host: String,
        port: Int
    ) {
        persistSignals(result.sdrSignals.toSdrSignalDevices())
        db.signalDeviceDao().insertAll(result.awareness.updatedDevices)
        _state.update {
            it.copy(
                sdrScanActive = false,
                networkSdrConnected = true,
                sdrDeviceName = "PC rtl_power $host:$port",
                awarenessDevices = result.awareness.updatedDevices,
                awarenessProfiles = result.awareness.profiles,
                awarenessSignalCount = result.awareness.totalSignals,
                awarenessSyncConnected = true,
                awarenessSyncInProgress = false,
                awarenessSyncStatus = "PC deep scan found ${result.sdrSignals.size} RF peak(s)"
            )
        }
    }

    fun setAwarenessSyncEndpoint(host: String, port: String) {
        _state.update {
            it.copy(
                awarenessSyncHost = host,
                awarenessSyncPort = port,
                networkSdrHost = host
            )
        }
        saveWindowsServerSettings()
    }

    fun setAwarenessSyncEnabled(enabled: Boolean) {
        _state.update {
            it.copy(
                awarenessSyncEnabled = enabled,
                awarenessSyncConnected = false,
                awarenessSyncStatus = if (enabled) "Manual sync ready" else "Sync off"
            )
        }
        saveWindowsServerSettings()
    }

    fun syncSavedAwarenessToWindows() {
        triggerAwarenessSync()
    }

    fun compactConfirmedPhoneHistory() {
        viewModelScope.launch {
            val removed = db.signalDeviceDao().deleteConfirmedSightings()
            _state.update {
                it.copy(
                    awarenessCompactionReadyCount = 0,
                    awarenessSyncStatus = if (removed > 0) {
                        "Compacted $removed PC-confirmed sightings; phone profiles retained"
                    } else {
                        "Nothing confirmed for compaction"
                    }
                )
            }
        }
    }

    fun connectAwarenessSyncServer() {
        val current = _state.value
        val host = current.awarenessSyncHost.ifBlank { current.networkSdrHost }
        val port = current.awarenessSyncPort.toIntOrNull() ?: 8765
        if (host.isBlank()) {
            _state.update { it.copy(awarenessSyncConnected = false, awarenessSyncStatus = "Enter PC host") }
            return
        }

        viewModelScope.launch {
            _state.update {
                it.copy(
                    awarenessSyncInProgress = true,
                    awarenessSyncStatus = "Connecting to PC..."
                )
            }
            runCatching {
                awarenessSyncClient.healthCheck(host, port)
            }.onSuccess { ok ->
                _state.update {
                    it.copy(
                        awarenessSyncConnected = ok,
                        awarenessSyncEnabled = ok || it.awarenessSyncEnabled,
                        awarenessSyncInProgress = false,
                        awarenessSyncStatus = if (ok) "PC sync connected" else "PC sync offline"
                    )
                }
                if (ok) {
                    saveWindowsServerSettings()
                }
            }.onFailure { error ->
                _state.update {
                    it.copy(
                        awarenessSyncConnected = false,
                        awarenessSyncInProgress = false,
                        awarenessSyncStatus = "Connect failed: ${error.message ?: "server unreachable"}"
                    )
                }
            }
        }
    }

    fun connectNetworkSdr() {
        val current = _state.value
        val port = current.networkSdrPort.toIntOrNull() ?: 1234
        if (current.networkSdrHost.isBlank()) {
            _state.update { it.copy(errorMessage = "Enter the PC host for Network SDR") }
            return
        }

        _state.update {
            it.copy(
                networkSdrConnected = true,
                sdrDeviceName = "rtl_tcp ${current.networkSdrHost}:$port",
                errorMessage = null
            )
        }
        saveWindowsServerSettings()
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

    private fun restoreWindowsServerSettings() {
        val savedNetworkHost = serverPrefs.getString(PREF_NETWORK_HOST, "").orEmpty()
        val networkPort = serverPrefs.getString(PREF_NETWORK_PORT, "1234").orEmpty().ifBlank { "1234" }
        val awarenessHost = serverPrefs.getString(PREF_AWARENESS_HOST, "").orEmpty().ifBlank { savedNetworkHost }
        val awarenessPort = serverPrefs.getString(PREF_AWARENESS_PORT, "8765").orEmpty().ifBlank { "8765" }
        val awarenessEnabled = serverPrefs.getBoolean(PREF_AWARENESS_ENABLED, false)

        _state.update {
            it.copy(
                networkSdrHost = awarenessHost,
                networkSdrPort = networkPort,
                awarenessSyncHost = awarenessHost,
                awarenessSyncPort = awarenessPort,
                awarenessSyncEnabled = awarenessEnabled,
                awarenessSyncStatus = if (awarenessEnabled) "Manual sync ready" else "Sync off"
            )
        }
    }

    private fun autoConnectWindowsServer() {
        val current = _state.value
        if (current.networkSdrHost.isNotBlank()) {
            connectNetworkSdr()
        }
        if (current.awarenessSyncEnabled) {
            _state.update { it.copy(awarenessSyncStatus = "Manual sync ready") }
        }
    }

    private fun saveWindowsServerSettings() {
        val current = _state.value
        val pcHost = current.awarenessSyncHost.ifBlank { current.networkSdrHost }.trim()
        serverPrefs.edit()
            .putString(PREF_NETWORK_HOST, pcHost)
            .putString(PREF_NETWORK_PORT, current.networkSdrPort.ifBlank { "1234" })
            .putString(PREF_AWARENESS_HOST, pcHost)
            .putString(PREF_AWARENESS_PORT, current.awarenessSyncPort.ifBlank { "8765" })
            .putBoolean(PREF_AWARENESS_ENABLED, current.awarenessSyncEnabled)
            .apply()
    }

    private fun loadPersistedSignals() {
        viewModelScope.launch {
            db.signalDeviceDao().getAllDevices().collect { devices ->
                applyPersistedSignalsToState(devices)
            }
        }
    }

    private fun loadCompactionState() {
        viewModelScope.launch {
            val confirmed = db.signalDeviceDao().countConfirmedSightings()
            _state.update { it.copy(awarenessCompactionReadyCount = confirmed) }
        }
    }

    private suspend fun persistSignals(devices: List<SignalDevice>) {
        detectionStore.record(devices)
    }

    private fun applyPersistedSignalsToState(devices: List<SignalDevice>) {
        val localDevices = devices.filter { !it.id.startsWith("awareness_") }
        _state.update {
            it.copy(
                wifiDevices = localDevices.filter { device -> device.signalType == SignalType.WIFI },
                bluetoothDevices = localDevices.filter { device -> device.signalType == SignalType.BLUETOOTH },
                bleDevices = localDevices.filter { device -> device.signalType == SignalType.BLE },
                cellTowers = localDevices.filter { device -> device.signalType == SignalType.CELLULAR }.map { device -> device.toCellTower() },
                sdrSignals = localDevices.filter { device -> device.signalType == SignalType.RTL_SDR }.map { device -> device.toSdrSignal() },
                lastNfcTag = localDevices.firstOrNull { device -> device.signalType == SignalType.NFC }?.toNfcTag(),
                awarenessSignalCount = devices.size,
                alertCount = it.summary.alertCount
            )
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

    private fun triggerAwarenessSync() {
        val current = _state.value
        val host = current.awarenessSyncHost.ifBlank { current.networkSdrHost }
        val port = current.awarenessSyncPort.toIntOrNull() ?: 8765
        if (host.isBlank()) {
            _state.update { it.copy(awarenessSyncConnected = false, awarenessSyncStatus = "Enter PC host") }
            return
        }

        viewModelScope.launch {
            _state.update {
                it.copy(
                    awarenessSyncInProgress = true,
                    awarenessSyncStatus = "Sending saved scan history..."
                )
            }
            val outbound = db.signalDeviceDao().getAllDevicesOnce()
                .filter { !it.id.startsWith("awareness_") }
            val sightings = db.signalDeviceDao().getUnsyncedSightings()
            runCatching {
                awarenessSyncClient.sync(host, port, outbound, sightings)
            }.onSuccess { result ->
                applyAwarenessSyncResult(result)
                if (result.acknowledgedSightingIds.isNotEmpty()) {
                    db.signalDeviceDao().markSightingsSynced(
                        result.acknowledgedSightingIds,
                        System.currentTimeMillis()
                    )
                }
                val confirmed = db.signalDeviceDao().countConfirmedSightings()
                _state.update {
                    it.copy(
                        awarenessSyncInProgress = false,
                        awarenessCompactionReadyCount = confirmed,
                        awarenessSyncStatus = "PC confirmed ${result.acknowledgedSightingIds.size}/${sightings.size} sightings; review then compact"
                    )
                }
            }.onFailure { error ->
                _state.update {
                    it.copy(
                        awarenessSyncConnected = it.awarenessSyncConnected,
                        awarenessSyncInProgress = false,
                        awarenessSyncStatus = if (error is SocketTimeoutException) {
                            "PC is busy; saved history queued locally"
                        } else {
                            "Sync offline: ${error.message ?: "connection failed"}"
                        }
                    )
                }
            }
        }
    }

    private suspend fun applyAwarenessSyncResult(result: com.snifferops.sync.AwarenessSyncResult) {
        if (result.updatedDevices.isNotEmpty()) {
            db.signalDeviceDao().insertAll(result.updatedDevices)
        }
        _state.update {
            it.copy(
                awarenessDevices = result.updatedDevices.ifEmpty { it.awarenessDevices },
                awarenessProfiles = result.profiles.ifEmpty { it.awarenessProfiles },
                awarenessSignalCount = result.totalSignals,
                awarenessSyncConnected = true
            )
        }
    }

    private fun syncWearState(appState: AppState) {
        val summary = appState.summary
        val awarenessProfiles = appState.compactAwarenessProfiles()
        val request = PutDataMapRequest.create("/snifferops/summary").apply {
            dataMap.putInt("wifi", summary.wifiCount)
            dataMap.putInt("bt", summary.bluetoothCount + summary.bleCount)
            dataMap.putInt("cell", summary.cellCount)
            dataMap.putInt("sdr", summary.sdrCount)
            dataMap.putInt("alerts", appState.alertTotal)
            dataMap.putInt("awareness", awarenessProfiles.size)
            dataMap.putBoolean("scanning", summary.scanActive)
            dataMap.putBoolean("sdr_connected", summary.sdrConnected)
            dataMap.putLong("updated_at", System.currentTimeMillis())
            dataMap.putStringArrayList("wifi_items", appState.wifiDevices.groupSignalDevices().toWearRows(8) { group ->
                val device = group.primary
                wearRow(
                    title = group.title,
                    detail = wearDetail(wearEstimatedType(group.typeLabel), wearCount(group.count), "Ch ${device.channel}"),
                    value = "${group.strongestSignal}"
                )
            })
            dataMap.putStringArrayList("bt_items", (appState.bluetoothDevices + appState.bleDevices).groupSignalDevices().toWearRows(8) { group ->
                wearRow(
                    title = group.title,
                    detail = wearDetail(wearEstimatedType(group.typeLabel), wearCount(group.count)),
                    value = "${group.strongestSignal}"
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
            dataMap.putStringArrayList("alert_items", appState.alertWearDevices().groupSignalDevices().toWearRows(8) { group ->
                val device = group.primary
                wearRow(
                    title = group.title,
                    detail = wearDetail(wearEstimatedType(group.typeLabel), wearCount(group.count), device.threatLevel.wearLabel()),
                    value = "${group.strongestSignal}"
                )
            })
            dataMap.putStringArrayList("awareness_items", awarenessProfiles.toWearRows(8) { profile ->
                wearRow(
                    title = profile.name,
                    detail = wearDetail(profile.status.wearLabel(), "${profile.seenCount}x", profile.latestEvent.ifBlank { profile.deviceClass }),
                    value = profile.source.uppercase()
                )
            })
        }.asPutDataRequest().setUrgent()

        wearDataClient.putDataItem(request)
            .addOnSuccessListener {
                Log.d(
                    TAG,
                    "Published summary scanning=${summary.scanActive} wifi=${summary.wifiCount} " +
                        "bt=${summary.bluetoothCount + summary.bleCount} cell=${summary.cellCount} " +
                        "sdr=${summary.sdrCount} alerts=${appState.alertTotal}"
                )
            }
            .addOnFailureListener { error ->
                Log.w(TAG, "Failed to publish summary", error)
            }
    }

    private fun AppState.alertWearDevices(): List<SignalDevice> =
        alertDevices.sortedByDescending { it.threatLevel.ordinal }

    private fun <T> List<T>.toWearRows(limit: Int, mapper: (T) -> String): ArrayList<String> =
        take(limit).mapTo(ArrayList(), mapper)

    private fun wearRow(title: String, detail: String, value: String): String =
        listOf(title, detail, value).joinToString("|") { it.cleanWearText() }

    private fun wearDetail(vararg parts: String): String =
        parts.filter { it.isNotBlank() && it != "Ch 0" }
            .joinToString("  ")

    private fun wearEstimatedType(type: String): String =
        type.takeIf { it.isNotBlank() }?.let { "$it*" } ?: ""

    private fun wearCount(count: Int): String =
        if (count > 1) "$count signals" else ""

    private fun ThreatLevel.wearLabel(): String = when (this) {
        ThreatLevel.ALERT -> "ALERT"
        ThreatLevel.SUSPICIOUS -> "WATCH"
        ThreatLevel.UNKNOWN -> "NOTICED"
        ThreatLevel.SAFE -> "SAFE"
    }

    private fun AwarenessStatus.wearLabel(): String = when (this) {
        AwarenessStatus.NORMAL -> "NORMAL"
        AwarenessStatus.LEARNING -> "LEARN"
        AwarenessStatus.NOTICED -> "NOTICED"
        AwarenessStatus.ONE_OFF -> "ONE-OFF"
        AwarenessStatus.WATCH -> "WATCH"
        AwarenessStatus.ALERT -> "ALERT"
    }

    private fun String.cleanWearText(): String =
        replace("|", "/").replace(Regex("\\s+"), " ").trim().take(32)

    private fun formatWearFrequency(hz: Long): String = when {
        hz >= 1_000_000_000L -> "${"%.2f".format(hz / 1_000_000_000.0)}G"
        hz >= 1_000_000L -> "${"%.1f".format(hz / 1_000_000.0)}M"
        hz >= 1_000L -> "${"%.0f".format(hz / 1_000.0)}K"
        else -> "$hz"
    }

private fun List<CellTower>.toCellSignalDevices(): List<SignalDevice> = map { tower ->
    SignalDevice(
        id = "cell_${tower.technology}_${tower.cid}_${tower.frequency}",
            name = tower.carrier.ifBlank { "${tower.technology} cell tower" },
            address = "CID ${tower.cid}",
            signalType = SignalType.CELLULAR,
            signalStrength = tower.signalStrength,
            frequency = tower.frequency,
            deviceClass = "${tower.technology} cell tower",
            threatLevel = ThreatLevel.UNKNOWN,
            notes = "MCC ${tower.mcc}; MNC ${tower.mnc}; LAC ${tower.lac}",
            firstSeen = tower.timestamp,
        lastSeen = tower.timestamp
    )
}

private fun SignalDevice.toCellTower(): CellTower {
    val mcc = Regex("MCC\\s+(\\d+)").find(notes)?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 0
    val mnc = Regex("MNC\\s+(\\d+)").find(notes)?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 0
    val lac = Regex("LAC\\s+(\\d+)").find(notes)?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 0
    val cid = address.removePrefix("CID ").toIntOrNull() ?: id.substringAfterLast("_").toIntOrNull() ?: 0
    return CellTower(
        mcc = mcc,
        mnc = mnc,
        lac = lac,
        cid = cid,
        signalStrength = signalStrength,
        technology = deviceClass.substringBefore(" cell tower").ifBlank { "CELL" },
        carrier = name,
        frequency = frequency,
        timestamp = lastSeen
    )
}

private fun List<SdrSignal>.toSdrSignalDevices(): List<SignalDevice> = map { signal ->
    SignalDevice(
        id = "sdr_${signal.frequency}",
            name = signal.label.ifBlank { "RF signal" },
            address = "${signal.frequency}",
            signalType = SignalType.RTL_SDR,
            signalStrength = signal.power.toInt(),
            frequency = signal.frequency,
            deviceClass = signal.label.ifBlank { "Measured RF signal" },
            threatLevel = ThreatLevel.UNKNOWN,
            notes = "Power ${signal.power} dB; ${signal.modulation}",
            firstSeen = signal.timestamp,
        lastSeen = signal.timestamp
    )
}

private fun SignalDevice.toSdrSignal(): SdrSignal = SdrSignal(
    frequency = frequency,
    power = signalStrength.toFloat(),
    modulation = notes.substringAfter("; ", "Unknown").ifBlank { "Unknown" },
    label = name,
    timestamp = lastSeen
)

private fun NfcTag.toSignalDevice(): SignalDevice = SignalDevice(
        id = "nfc_$id",
        name = type.ifBlank { "NFC tag" },
        address = id,
        signalType = SignalType.NFC,
        signalStrength = 0,
        deviceClass = technologies.joinToString(", ").ifBlank { "NFC tag" },
        threatLevel = ThreatLevel.UNKNOWN,
        notes = data,
        firstSeen = timestamp,
    lastSeen = timestamp
)

private fun SignalDevice.toNfcTag(): NfcTag = NfcTag(
    id = address.ifBlank { id.removePrefix("nfc_") },
    technologies = deviceClass.split(",").map { it.trim() }.filter { it.isNotBlank() },
    type = name,
    data = notes,
    timestamp = lastSeen
)

    override fun onCleared() {
        super.onCleared()
        wifiJob?.cancel()
        btJob?.cancel()
        bleJob?.cancel()
        cellJob?.cancel()
        sdrJob?.cancel()
        sdrCheckJob?.cancel()
        pcSdrScanJob?.cancel()
    }
}

fun AppState.compactAwarenessProfiles(): List<AwarenessProfile> {
    val local = (wifiDevices + bluetoothDevices + bleDevices).map { it.toAwarenessProfile("local") } +
        cellTowers.map { it.toAwarenessProfile() } +
        sdrSignals.map { it.toAwarenessProfile() } +
        listOfNotNull(lastNfcTag?.toAwarenessProfile())

    return (awarenessProfiles + local)
        .groupBy { it.key.ifBlank { "${it.type}:${it.name}" } }
        .map { (_, profiles) -> profiles.maxByOrNull { it.lastSeen } ?: profiles.first() }
        .sortedWith(compareBy<AwarenessProfile> {
            when (it.status) {
                AwarenessStatus.ALERT -> 0
                AwarenessStatus.WATCH -> 0
                AwarenessStatus.NOTICED -> 1
                AwarenessStatus.ONE_OFF -> 2
                AwarenessStatus.LEARNING -> 2
                AwarenessStatus.NORMAL -> 3
            }
        }.thenByDescending { it.lastSeen })
}

private fun SignalDevice.toAwarenessProfile(source: String): AwarenessProfile = AwarenessProfile(
    key = "${signalType.name}|${address.ifBlank { id }}",
    name = name.ifBlank { signalType.name },
    type = signalType,
    deviceClass = deviceClass.ifBlank { signalType.name },
    threatLevel = threatLevel,
    seenCount = seenCount,
    nodeCount = 1,
    lastSeen = lastSeen,
    latestEvent = notes.ifBlank { "Seen locally" },
    latitude = latitude,
    longitude = longitude,
    source = source
)

fun SignalDevice.isAlertRelevant(): Boolean {
    val text = listOf(name, signalType.name, deviceClass, manufacturer, notes)
        .joinToString(" ")
        .lowercase()
    val highPattern = Regex("imsi|stingray|fake\\s*sim|fake\\s*cell|rogue\\s*cell|cell\\s*site\\s*simulator|evil\\s*twin|wifi\\s*pineapple|pineapple|deauther|pwnagotchi|marauder|flipper|badusb|skimmer|tap\\s*to\\s*pay|payment|nfc\\s*intercept|credential|password|phish|sniffer|data[- ]?capture|hacking")
    val mediumPattern = Regex("flock|flock\\s*safety|alpr|lpr|license\\s*plate|plate\\s*reader|traffic\\s*reader|traffic\\s*camera|speed\\s*camera|red\\s*light|surveillance|cctv|doorbell|verkada|avigilon|hikvision|dahua|axis|vigilant|genetec|motorola")
    val lowPattern = Regex("unknown\\s*ble|beacon|tracker|airtag|tile|hidden\\s*wifi|open\\s*wifi|open\\s*security|unsecured|rogue|spoof|jam|burst|unexpected|odd|weird")

    return when (threatLevel) {
        ThreatLevel.ALERT -> true
        ThreatLevel.SUSPICIOUS -> true
        ThreatLevel.UNKNOWN -> highPattern.containsMatchIn(text) ||
            mediumPattern.containsMatchIn(text) ||
            (seenCount < 5 && lowPattern.containsMatchIn(text))
        ThreatLevel.SAFE -> highPattern.containsMatchIn(text) || mediumPattern.containsMatchIn(text)
    }
}

private fun CellTower.toAwarenessProfile(): AwarenessProfile = AwarenessProfile(
    key = "CELLULAR|${technology}|${cid}",
    name = carrier.ifBlank { "$technology cell tower" },
    type = SignalType.CELLULAR,
    deviceClass = "$technology cell tower",
    threatLevel = ThreatLevel.UNKNOWN,
    seenCount = 1,
    nodeCount = 1,
    lastSeen = timestamp,
    latestEvent = "Seen locally at CID $cid",
    source = "local"
)

private fun SdrSignal.toAwarenessProfile(): AwarenessProfile = AwarenessProfile(
    key = "RTL_SDR|${frequency / 250_000L}",
    name = label.ifBlank { "RF signal" },
    type = SignalType.RTL_SDR,
    deviceClass = label.ifBlank { "Measured RF signal" },
    threatLevel = ThreatLevel.UNKNOWN,
    seenCount = 1,
    nodeCount = 1,
    lastSeen = timestamp,
    latestEvent = "Measured ${power} dB ${modulation}",
    source = "local"
)

private fun NfcTag.toAwarenessProfile(): AwarenessProfile = AwarenessProfile(
    key = "NFC|$id",
    name = type.ifBlank { "NFC tag" },
    type = SignalType.NFC,
    deviceClass = technologies.joinToString(", ").ifBlank { "NFC tag" },
    threatLevel = ThreatLevel.UNKNOWN,
    seenCount = 1,
    nodeCount = 1,
    lastSeen = timestamp,
    latestEvent = "NFC tag read locally",
    source = "local"
)
