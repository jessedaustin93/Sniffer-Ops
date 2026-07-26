package com.ethrox.detect.viewmodel

import android.app.Application
import android.content.Context
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.ethrox.detect.data.AppDatabase
import com.ethrox.detect.data.SignalDetectionStore
import com.ethrox.detect.model.*
import com.ethrox.detect.scanner.*
import com.ethrox.detect.sync.AwarenessSyncClient
import com.ethrox.detect.util.groupSignalDevices
import com.ethrox.detect.util.sortedForLocalDisplay
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import java.net.SocketTimeoutException

data class AppState(
    val historyDevices: List<SignalDevice> = emptyList(),
    val wifiDevices: List<SignalDevice> = emptyList(),
    val bluetoothDevices: List<SignalDevice> = emptyList(),
    val bleDevices: List<SignalDevice> = emptyList(),
    val cellTowers: List<CellTower> = emptyList(),
    val lastNfcTag: NfcTag? = null,
    val awarenessSyncHost: String = "",
    val awarenessSyncPort: String = "8766",
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
    val alertCount: Int = 0,
    val errorMessage: String? = null
) {
    val summary: ScanSummary get() = ScanSummary(
        wifiCount = wifiDevices.size,
        bluetoothCount = bluetoothDevices.size,
        bleCount = bleDevices.size,
        nfcCount = if (lastNfcTag != null) 1 else 0,
        cellCount = cellTowers.size,
        noticedCount = alertDevices.count { it.threatLevel == ThreatLevel.UNKNOWN },
        suspiciousCount = alertDevices.count { it.threatLevel == ThreatLevel.SUSPICIOUS },
        alertCount = alertDevices.count { it.threatLevel == ThreatLevel.ALERT },
        scanActive = scanActive
    )

    val alertTotal: Int get() = summary.alertCount + summary.suspiciousCount + summary.noticedCount
    val alertDevices: List<SignalDevice> get() =
        (wifiDevices + bluetoothDevices + bleDevices + awarenessDevices).filter { it.isAlertRelevant() }
}

@OptIn(FlowPreview::class)
class DashboardViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        private const val TAG = "EthroxDetectWearSync"
        private const val SERVER_PREFS = "ethrox_detect_endpoints"
        private const val PREF_AWARENESS_HOST = "awareness_sync_host"
        private const val PREF_AWARENESS_PORT = "awareness_sync_port"
        private const val PREF_AWARENESS_ENABLED = "awareness_sync_enabled"
        private const val DEFAULT_T5810B_HUB_HOST = ""
        private const val DEFAULT_T5810B_HUB_PORT = "8766"
        private const val LIVE_REFRESH_INTERVAL_MS = 2_000L
        private const val LIVE_STATE_LIMIT = 300
        private const val PERSIST_BATCH_DELAY_MS = 5_000L
        private const val WIFI_LIVE_WINDOW_MS = 45_000L
        private const val BLUETOOTH_LIVE_WINDOW_MS = 20_000L
        private const val CELLULAR_LIVE_WINDOW_MS = 45_000L
        private const val NFC_LIVE_WINDOW_MS = 2 * 60_000L
    }

    private val appContext = application.applicationContext
    private val serverPrefs = appContext.getSharedPreferences(SERVER_PREFS, Context.MODE_PRIVATE)
    private val db = AppDatabase.getInstance(application)
    private val wearDataClient = Wearable.getDataClient(application)
    private val wifiScanner = WifiScanner(application)
    private val btScanner = BluetoothScanner(application)
    private val cellularScanner = CellularScanner(application)
    private val awarenessSyncClient = AwarenessSyncClient(application)
    private val detectionStore = SignalDetectionStore(application)

    private val _state = MutableStateFlow(AppState())
    val state: StateFlow<AppState> = _state.asStateFlow()

    private var wifiJob: Job? = null
    private var btJob: Job? = null
    private var bleJob: Job? = null
    private var cellJob: Job? = null
    private var persistBatchJob: Job? = null
    private var persistedDevices: List<SignalDevice> = emptyList()
    private val liveDevicesById = LinkedHashMap<String, SignalDevice>()
    private val pendingPersistById = LinkedHashMap<String, SignalDevice>()

    init {
        restoreEndpointSettings()
        loadPersistedSignals()
        startLivePresenceRefresh()
        loadCompactionState()
        startWearSync()
        autoConnectLinuxHub()
    }

    fun startAllScans() {
        _state.update {
            it.copy(
                scanActive = true,
                wifiScanActive = true,
                btScanActive = true,
                bleScanActive = true,
                cellScanActive = true
            )
        }
        startWifiScan()
        startBluetoothScan()
        startBleScan()
        startCellularScan()
    }

    fun stopAllScans() {
        wifiJob?.cancel(); wifiJob = null
        btJob?.cancel(); btJob = null
        bleJob?.cancel(); bleJob = null
        cellJob?.cancel(); cellJob = null
        _state.update { it.copy(
            scanActive = false,
            wifiScanActive = false,
            btScanActive = false,
            bleScanActive = false,
            cellScanActive = false
        ) }
    }

    fun startWifiScan() {
        if (wifiJob?.isActive == true) {
            _state.update { it.copy(wifiScanActive = true) }
            return
        }
        wifiJob?.cancel()
        _state.update { it.copy(wifiScanActive = true) }
        wifiJob = viewModelScope.launch {
            wifiScanner.scan().collect { devices ->
                recordLiveSignals(devices)
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
        if (btJob?.isActive == true) {
            _state.update { it.copy(btScanActive = true) }
            return
        }
        btJob?.cancel()
        _state.update { it.copy(btScanActive = true) }
        btJob = viewModelScope.launch {
            btScanner.scanClassic().collect { devices ->
                recordLiveSignals(devices)
            }
        }
    }

    fun stopBluetoothScan() {
        btJob?.cancel(); btJob = null
        _state.update { it.copy(btScanActive = false) }
    }

    fun startBleScan() {
        if (bleJob?.isActive == true) {
            _state.update { it.copy(bleScanActive = true) }
            return
        }
        bleJob?.cancel()
        _state.update { it.copy(bleScanActive = true) }
        bleJob = viewModelScope.launch {
            btScanner.scanBle().collect { devices ->
                recordLiveSignals(devices)
            }
        }
    }

    fun stopBleScan() {
        bleJob?.cancel(); bleJob = null
        _state.update { it.copy(bleScanActive = false) }
    }

    fun startCellularScan() {
        if (cellJob?.isActive == true) {
            _state.update { it.copy(cellScanActive = true) }
            return
        }
        cellJob?.cancel()
        _state.update { it.copy(cellScanActive = true) }
        cellJob = viewModelScope.launch {
            cellularScanner.scan().collect { towers ->
                recordLiveSignals(towers.toCellSignalDevices())
            }
        }
    }

    fun stopCellularScan() {
        cellJob?.cancel(); cellJob = null
        _state.update { it.copy(cellScanActive = false) }
    }

    fun onNfcTagDetected(tag: com.ethrox.detect.model.NfcTag) {
        viewModelScope.launch {
            recordLiveSignals(listOf(tag.toSignalDevice()))
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

    fun setAwarenessSyncEndpoint(host: String, port: String) {
        _state.update {
            it.copy(
                awarenessSyncHost = host,
                awarenessSyncPort = port
            )
        }
        saveEndpointSettings()
    }

    fun setAwarenessSyncEnabled(enabled: Boolean) {
        _state.update {
            it.copy(
                awarenessSyncEnabled = enabled,
                awarenessSyncConnected = false,
                awarenessSyncStatus = if (enabled) "T5810B hub sync ready" else "Sync off"
            )
        }
        saveEndpointSettings()
    }

    fun syncSavedAwarenessToHub() {
        triggerAwarenessSync()
    }

    fun compactConfirmedPhoneHistory() {
        viewModelScope.launch {
            val wasScanning = _state.value.scanActive
            if (wasScanning) stopAllScans()
            _state.update {
                it.copy(
                    awarenessSyncInProgress = true,
                    awarenessSyncStatus = "Compacting hub-confirmed sightings..."
                )
            }
            val removed = withContext(Dispatchers.IO) {
                db.signalDeviceDao().deleteConfirmedSightings()
            }
            val remainingConfirmed = withContext(Dispatchers.IO) {
                db.signalDeviceDao().countConfirmedSightings()
            }
            _state.update {
                it.copy(
                    awarenessSyncInProgress = false,
                    awarenessCompactionReadyCount = remainingConfirmed,
                    awarenessSyncStatus = if (removed > 0) {
                        "Compacted $removed hub-confirmed sightings; phone profiles retained"
                    } else {
                        "Nothing confirmed for compaction"
                    }
                )
            }
            if (wasScanning) {
                delay(750)
                startAllScans()
            }
        }
    }

    fun connectAwarenessSyncServer() {
        val current = _state.value
        val host = current.awarenessSyncHost
        val port = current.awarenessSyncPort.toIntOrNull() ?: 8766
        if (host.isBlank()) {
            _state.update { it.copy(awarenessSyncConnected = false, awarenessSyncStatus = "Enter T5810B Tailscale host") }
            return
        }

        viewModelScope.launch {
            _state.update {
                it.copy(
                    awarenessSyncInProgress = true,
                    awarenessSyncStatus = "Connecting to T5810B hub..."
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
                        awarenessSyncStatus = if (ok) "T5810B hub connected" else "T5810B hub offline"
                    )
                }
                if (ok) {
                    saveEndpointSettings()
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

    private fun restoreEndpointSettings() {
        val awarenessHost = serverPrefs
            .getString(PREF_AWARENESS_HOST, DEFAULT_T5810B_HUB_HOST)
            .orEmpty()
            .ifBlank { DEFAULT_T5810B_HUB_HOST }
        val awarenessPort = serverPrefs
            .getString(PREF_AWARENESS_PORT, DEFAULT_T5810B_HUB_PORT)
            .orEmpty()
            .ifBlank { DEFAULT_T5810B_HUB_PORT }
        val awarenessEnabled = serverPrefs.getBoolean(PREF_AWARENESS_ENABLED, true)

        _state.update {
            it.copy(
                awarenessSyncHost = awarenessHost,
                awarenessSyncPort = awarenessPort,
                awarenessSyncEnabled = awarenessEnabled,
                awarenessSyncStatus = if (awarenessEnabled) "T5810B hub sync ready" else "Sync off"
            )
        }
    }

    private fun autoConnectLinuxHub() {
        val current = _state.value
        if (current.awarenessSyncEnabled) {
            _state.update { it.copy(awarenessSyncStatus = "T5810B hub sync ready") }
        }
    }

    private fun saveEndpointSettings() {
        val current = _state.value
        serverPrefs.edit()
            .putString(PREF_AWARENESS_HOST, current.awarenessSyncHost.trim())
            .putString(PREF_AWARENESS_PORT, current.awarenessSyncPort.ifBlank { DEFAULT_T5810B_HUB_PORT })
            .putBoolean(PREF_AWARENESS_ENABLED, current.awarenessSyncEnabled)
            .apply()
    }

    private fun loadPersistedSignals() {
        viewModelScope.launch {
            db.signalDeviceDao().getAllDevices()
                .conflate()
                .debounce(250)
                .collect { devices ->
                    persistedDevices = devices.take(1_000)
                    applyPersistedHistoryToState(devices)
                }
        }
    }

    private fun startLivePresenceRefresh() {
        viewModelScope.launch {
            while (isActive) {
                delay(LIVE_REFRESH_INTERVAL_MS)
                pruneAndPublishLiveSignals()
            }
        }
    }

    private fun loadCompactionState() {
        viewModelScope.launch {
            val confirmed = db.signalDeviceDao().countConfirmedSightings()
            _state.update { it.copy(awarenessCompactionReadyCount = confirmed) }
        }
    }

    private fun recordLiveSignals(devices: List<SignalDevice>) {
        if (devices.isEmpty()) return
        val now = System.currentTimeMillis()
        val stamped = devices.map { device ->
            device.copy(
                firstSeen = if (device.firstSeen > 0L) device.firstSeen else now,
                lastSeen = now
            )
        }
        synchronized(liveDevicesById) {
            stamped.forEach { liveDevicesById[it.id] = it }
            trimLiveDeviceCacheLocked()
        }
        synchronized(pendingPersistById) {
            stamped.forEach { pendingPersistById[it.id] = it }
        }
        publishLiveSignals(now)
        schedulePersistFlush()
    }

    private fun applyPersistedHistoryToState(devices: List<SignalDevice>) {
        val localDevices = devices.filter { !it.id.startsWith("awareness_") }
        _state.update {
            it.copy(
                historyDevices = localDevices.take(1_000),
                awarenessSignalCount = devices.size,
                alertCount = it.summary.alertCount
            )
        }
    }

    private fun schedulePersistFlush() {
        if (persistBatchJob?.isActive == true) return
        persistBatchJob = viewModelScope.launch {
            delay(PERSIST_BATCH_DELAY_MS)
            flushPendingPersist()
        }
    }

    private suspend fun flushPendingPersist() {
        val batch = synchronized(pendingPersistById) {
            pendingPersistById.values.toList().also { pendingPersistById.clear() }
        }
        if (batch.isEmpty()) return
        withContext(Dispatchers.IO) {
            detectionStore.record(batch)
        }
    }

    private fun pruneAndPublishLiveSignals() {
        publishLiveSignals(System.currentTimeMillis())
    }

    private fun publishLiveSignals(now: Long) {
        val localDevices = synchronized(liveDevicesById) {
            liveDevicesById.entries.removeAll { (_, device) ->
                now - device.lastSeen > maxOf(WIFI_LIVE_WINDOW_MS, BLUETOOTH_LIVE_WINDOW_MS, CELLULAR_LIVE_WINDOW_MS, NFC_LIVE_WINDOW_MS)
            }
            liveDevicesById.values.toList()
        }
        _state.update {
            it.copy(
                wifiDevices = localDevices.liveSince(now, WIFI_LIVE_WINDOW_MS, SignalType.WIFI)
                    .sortedForLocalDisplay()
                    .take(LIVE_STATE_LIMIT),
                bluetoothDevices = localDevices.liveSince(now, BLUETOOTH_LIVE_WINDOW_MS, SignalType.BLUETOOTH)
                    .sortedForLocalDisplay()
                    .take(LIVE_STATE_LIMIT),
                bleDevices = localDevices.liveSince(now, BLUETOOTH_LIVE_WINDOW_MS, SignalType.BLE)
                    .sortedForLocalDisplay()
                    .take(LIVE_STATE_LIMIT),
                cellTowers = localDevices.liveSince(now, CELLULAR_LIVE_WINDOW_MS, SignalType.CELLULAR)
                    .sortedForLocalDisplay()
                    .take(LIVE_STATE_LIMIT)
                    .map { device -> device.toCellTower() },
                lastNfcTag = localDevices
                    .liveSince(now, NFC_LIVE_WINDOW_MS, SignalType.NFC)
                    .firstOrNull()
                    ?.toNfcTag()
            )
        }
    }

    private fun trimLiveDeviceCacheLocked() {
        while (liveDevicesById.size > LIVE_STATE_LIMIT * 5) {
            val firstKey = liveDevicesById.keys.firstOrNull() ?: break
            liveDevicesById.remove(firstKey)
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
        val host = current.awarenessSyncHost
        val port = current.awarenessSyncPort.toIntOrNull() ?: 8766
        if (host.isBlank()) {
            _state.update { it.copy(awarenessSyncConnected = false, awarenessSyncStatus = "Enter T5810B Tailscale host") }
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
                        awarenessSyncStatus = "T5810B hub confirmed ${result.acknowledgedSightingIds.size}/${sightings.size} sightings; review then compact"
                    )
                }
            }.onFailure { error ->
                _state.update {
                    it.copy(
                        awarenessSyncConnected = it.awarenessSyncConnected,
                        awarenessSyncInProgress = false,
                        awarenessSyncStatus = if (error is SocketTimeoutException) {
                            "T5810B hub unreachable/busy; saved history queued locally"
                        } else {
                            "Sync offline: ${error.message ?: "connection failed"}"
                        }
                    )
                }
            }
        }
    }

    private suspend fun applyAwarenessSyncResult(result: com.ethrox.detect.sync.AwarenessSyncResult) {
        if (result.updatedDevices.isNotEmpty()) {
            db.signalDeviceDao().insertAll(result.updatedDevices)
        }
        _state.update {
            it.copy(
                awarenessDevices = result.updatedDevices
                    .ifEmpty { it.awarenessDevices }
                    .sortedForLocalDisplay()
                    .take(LIVE_STATE_LIMIT),
                awarenessProfiles = result.profiles
                    .ifEmpty { it.awarenessProfiles }
                    .sortedWith(compareBy<AwarenessProfile> { profile ->
                        when (profile.status) {
                            AwarenessStatus.ALERT -> 0
                            AwarenessStatus.WATCH -> 0
                            AwarenessStatus.NOTICED -> 1
                            AwarenessStatus.ONE_OFF -> 2
                            AwarenessStatus.LEARNING -> 2
                            AwarenessStatus.NORMAL -> 3
                        }
                    }.thenByDescending { profile -> profile.lastSeen })
                    .take(LIVE_STATE_LIMIT),
                awarenessSignalCount = result.totalSignals,
                awarenessSyncConnected = true
            )
        }
    }

    private fun syncWearState(appState: AppState) {
        val summary = appState.summary
        val awarenessProfiles = appState.compactAwarenessProfiles()
        val request = PutDataMapRequest.create("/ethrox-detect/summary").apply {
            dataMap.putInt("wifi", summary.wifiCount)
            dataMap.putInt("bt", summary.bluetoothCount + summary.bleCount)
            dataMap.putInt("cell", summary.cellCount)
            dataMap.putInt("alerts", appState.alertTotal)
            dataMap.putInt("awareness", awarenessProfiles.size)
            dataMap.putBoolean("scanning", summary.scanActive)
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
                        "alerts=${appState.alertTotal}"
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
        persistBatchJob?.cancel()
    }
}

fun AppState.compactAwarenessProfiles(): List<AwarenessProfile> {
    val local = historyDevices.map { it.toAwarenessProfile("local-history") }

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

private fun List<SignalDevice>.liveSince(
    now: Long,
    windowMs: Long,
    type: SignalType
): List<SignalDevice> = filter { device ->
    device.signalType == type && now - device.lastSeen <= windowMs
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
