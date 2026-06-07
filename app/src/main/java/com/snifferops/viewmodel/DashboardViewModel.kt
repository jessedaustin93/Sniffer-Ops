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
import com.snifferops.sync.AwarenessSyncClient
import com.snifferops.util.groupSignalDevices
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
    val awarenessSyncHost: String = "",
    val awarenessSyncPort: String = "8765",
    val awarenessSyncEnabled: Boolean = false,
    val awarenessSyncConnected: Boolean = false,
    val awarenessSyncStatus: String = "Sync off",
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
    }

    private val db = AppDatabase.getInstance(application)
    private val wearDataClient = Wearable.getDataClient(application)
    private val wifiScanner = WifiScanner(application)
    private val btScanner = BluetoothScanner(application)
    private val cellularScanner = CellularScanner(application)
    val sdrScanner = RtlSdrScanner(application)
    private val networkSdrScanner = NetworkRtlSdrScanner()
    private val awarenessSyncClient = AwarenessSyncClient(application)

    private val _state = MutableStateFlow(AppState())
    val state: StateFlow<AppState> = _state.asStateFlow()

    private var wifiJob: Job? = null
    private var btJob: Job? = null
    private var bleJob: Job? = null
    private var cellJob: Job? = null
    private var sdrJob: Job? = null
    private var sdrCheckJob: Job? = null
    private var awarenessSyncJob: Job? = null

    init {
        checkSdrConnection()
        startSdrConnectionMonitor()
        startWearSync()
        startAwarenessSyncLoop()
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

    fun setAwarenessSyncEndpoint(host: String, port: String) {
        _state.update { it.copy(awarenessSyncHost = host, awarenessSyncPort = port) }
    }

    fun setAwarenessSyncEnabled(enabled: Boolean) {
        _state.update {
            it.copy(
                awarenessSyncEnabled = enabled,
                awarenessSyncConnected = false,
                awarenessSyncStatus = if (enabled) "Sync waiting" else "Sync off"
            )
        }
        if (enabled) {
            triggerAwarenessSync()
        }
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

    private fun startAwarenessSyncLoop() {
        awarenessSyncJob?.cancel()
        awarenessSyncJob = viewModelScope.launch {
            while (isActive) {
                delay(15_000)
                triggerAwarenessSync()
            }
        }
    }

    private fun triggerAwarenessSync() {
        val current = _state.value
        if (!current.awarenessSyncEnabled) return
        val host = current.awarenessSyncHost.ifBlank { current.networkSdrHost }
        val port = current.awarenessSyncPort.toIntOrNull() ?: 8765
        if (host.isBlank()) {
            _state.update { it.copy(awarenessSyncConnected = false, awarenessSyncStatus = "Enter Windows IP") }
            return
        }

        viewModelScope.launch {
            val snapshotState = _state.value
            val outbound = (snapshotState.wifiDevices + snapshotState.bluetoothDevices + snapshotState.bleDevices)
                .plus(snapshotState.cellTowers.toCellSignalDevices())
                .plus(snapshotState.sdrSignals.toSdrSignalDevices())
                .plus(listOfNotNull(snapshotState.lastNfcTag?.toSignalDevice()))
            runCatching {
                awarenessSyncClient.sync(host, port, outbound)
            }.onSuccess { result ->
                db.signalDeviceDao().insertAll(result.updatedDevices)
                _state.update {
                    it.copy(
                        awarenessDevices = result.updatedDevices,
                        awarenessProfiles = result.profiles,
                        awarenessSignalCount = result.totalSignals,
                        awarenessSyncConnected = true,
                        awarenessSyncStatus = "Synced ${result.merged} scan signal(s), ${result.totalSignals} known"
                    )
                }
            }.onFailure { error ->
                _state.update {
                    it.copy(
                        awarenessSyncConnected = false,
                        awarenessSyncStatus = "Sync offline: ${error.message ?: "connection failed"}"
                    )
                }
            }
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
        AwarenessStatus.ONE_OFF -> "ONE-OFF"
        AwarenessStatus.WATCH -> "WATCH"
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

    override fun onCleared() {
        super.onCleared()
        stopAllScans()
        sdrCheckJob?.cancel()
        awarenessSyncJob?.cancel()
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
                AwarenessStatus.WATCH -> 0
                AwarenessStatus.ONE_OFF -> 1
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
    val mediumPattern = Regex("flock|flock\\s*safety|alpr|lpr|license\\s*plate|plate\\s*reader|traffic\\s*reader|traffic\\s*camera|speed\\s*camera|red\\s*light|surveillance|cctv|camera|doorbell|verkada|avigilon|hikvision|dahua|axis|vigilant|genetec|motorola")
    val lowPattern = Regex("unknown\\s*ble|beacon|tracker|airtag|tile|hidden\\s*wifi|open\\s*wifi|open\\s*security|unsecured|rogue|spoof|jam|burst|unexpected|odd|weird")

    return when (threatLevel) {
        ThreatLevel.ALERT -> true
        ThreatLevel.SUSPICIOUS -> true
        ThreatLevel.UNKNOWN -> highPattern.containsMatchIn(text) ||
            mediumPattern.containsMatchIn(text) ||
            lowPattern.containsMatchIn(text)
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
