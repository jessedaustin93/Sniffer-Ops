package com.snifferops.scanner

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.WifiManager
import android.os.Build
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalType
import com.snifferops.util.DeviceClassifier
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

class WifiScanner(private val context: Context) {

    private val wifiManager = context.getSystemService(Context.WIFI_SERVICE) as WifiManager

    fun scan(): Flow<List<SignalDevice>> = callbackFlow {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context?, intent: Intent?) {
                if (intent?.action == WifiManager.SCAN_RESULTS_AVAILABLE_ACTION) {
                    val results = try {
                        @Suppress("DEPRECATION")
                        wifiManager.scanResults ?: emptyList()
                    } catch (e: SecurityException) {
                        emptyList()
                    }

                    val devices = results.map { result ->
                        val ssid = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            result.wifiSsid?.toString()?.trim('"') ?: "<hidden>"
                        } else {
                            @Suppress("DEPRECATION")
                            result.SSID?.ifEmpty { "<hidden>" } ?: "<hidden>"
                        }
                        val bssid = result.BSSID ?: ""
                        val capabilities = result.capabilities ?: ""
                        val (manufacturer, deviceClass, threat) = DeviceClassifier.classifyWifi(ssid, bssid, capabilities)

                        SignalDevice(
                            id = "wifi_$bssid",
                            name = ssid,
                            address = bssid,
                            signalType = SignalType.WIFI,
                            signalStrength = result.level,
                            frequency = result.frequency.toLong() * 1000,
                            manufacturer = manufacturer,
                            deviceClass = deviceClass,
                            isEncrypted = capabilities.contains("WPA") || capabilities.contains("WEP"),
                            channel = frequencyToChannel(result.frequency),
                            threatLevel = threat,
                            notes = capabilities
                        )
                    }
                    trySend(devices)
                }
            }
        }

        val filter = IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)
        context.registerReceiver(receiver, filter)

        try {
            @Suppress("DEPRECATION")
            wifiManager.startScan()
        } catch (_: Exception) {}

        awaitClose { context.unregisterReceiver(receiver) }
    }

    fun triggerScan(): Boolean = try {
        @Suppress("DEPRECATION")
        wifiManager.startScan()
    } catch (_: Exception) { false }

    private fun frequencyToChannel(freq: Int): Int = when {
        freq in 2412..2484 -> (freq - 2412) / 5 + 1
        freq in 5180..5825 -> (freq - 5000) / 5
        else -> 0
    }
}
