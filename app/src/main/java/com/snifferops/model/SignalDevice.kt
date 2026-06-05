package com.snifferops.model

import androidx.room.Entity
import androidx.room.PrimaryKey

enum class SignalType {
    WIFI, BLUETOOTH, BLE, NFC, CELLULAR, RTL_SDR, UNKNOWN
}

enum class ThreatLevel {
    SAFE, UNKNOWN, SUSPICIOUS, ALERT
}

@Entity(tableName = "signal_devices")
data class SignalDevice(
    @PrimaryKey val id: String,
    val name: String,
    val address: String,
    val signalType: SignalType,
    val signalStrength: Int,          // dBm
    val frequency: Long = 0L,         // Hz (for SDR/cellular)
    val manufacturer: String = "",
    val deviceClass: String = "",
    val isEncrypted: Boolean = false,
    val channel: Int = 0,
    val latitude: Double = 0.0,
    val longitude: Double = 0.0,
    val threatLevel: ThreatLevel = ThreatLevel.UNKNOWN,
    val notes: String = "",
    val firstSeen: Long = System.currentTimeMillis(),
    val lastSeen: Long = System.currentTimeMillis(),
    val seenCount: Int = 1
)

data class SdrSignal(
    val frequency: Long,              // Hz
    val bandwidth: Long = 0L,
    val power: Float,                 // dB
    val modulation: String = "Unknown",
    val label: String = "",
    val timestamp: Long = System.currentTimeMillis()
)

data class CellTower(
    val mcc: Int,
    val mnc: Int,
    val lac: Int,
    val cid: Int,
    val signalStrength: Int,
    val technology: String,           // GSM, WCDMA, LTE, NR
    val carrier: String = "",
    val frequency: Long = 0L,
    val timestamp: Long = System.currentTimeMillis()
)

data class NfcTag(
    val id: String,
    val technologies: List<String>,
    val type: String,
    val data: String = "",
    val timestamp: Long = System.currentTimeMillis()
)

data class ScanSummary(
    val wifiCount: Int = 0,
    val bluetoothCount: Int = 0,
    val bleCount: Int = 0,
    val nfcCount: Int = 0,
    val cellCount: Int = 0,
    val sdrCount: Int = 0,
    val suspiciousCount: Int = 0,
    val alertCount: Int = 0,
    val sdrConnected: Boolean = false,
    val scanActive: Boolean = false,
    val lastUpdate: Long = System.currentTimeMillis()
)
