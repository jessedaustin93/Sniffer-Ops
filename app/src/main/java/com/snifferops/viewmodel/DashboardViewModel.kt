package com.snifferops.viewmodel

import android.app.Application
import android.content.Context
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
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
    val sdrDeviceName: String = "",
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
        sdrConnected = sdrConnected,
        scanActive = scanActive
    )
}

class DashboardViewModel(application: Application) : AndroidViewModel(application) {

    private val db = AppDatabase.getInstance(application)
    private val wifiScanner = WifiScanner(application)
    private val btScanner = BluetoothScanner(application)
    private val cellularScanner = CellularScanner(application)
    val sdrScanner = RtlSdrScanner(application)

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
        if (!_state.value.sdrConnected) return
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
            _state.update { AppState(sdrConnected = it.sdrConnected, sdrDeviceName = it.sdrDeviceName) }
        }
    }

    fun onUsbDeviceAttached(device: UsbDevice) {
        checkSdrConnection()
    }

    fun onUsbDeviceDetached(device: UsbDevice) {
        stopSdrScan()
        _state.update { it.copy(sdrConnected = false, sdrDeviceName = "") }
    }

    private fun checkSdrConnection() {
        val connected = sdrScanner.isConnected()
        _state.update { it.copy(
            sdrConnected = connected,
            sdrDeviceName = if (connected) sdrScanner.getDeviceName() else ""
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

    override fun onCleared() {
        super.onCleared()
        stopAllScans()
        sdrCheckJob?.cancel()
    }
}
