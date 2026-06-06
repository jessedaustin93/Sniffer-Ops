package com.snifferops.scanner

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.WifiManager
import android.os.Build
import android.util.Log
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalType
import com.snifferops.model.ThreatLevel
import com.snifferops.util.DeviceClassifier
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch

class WifiScanner(private val context: Context) {

    private val wifiManager = context.getSystemService(Context.WIFI_SERVICE) as WifiManager

    fun scan(): Flow<List<SignalDevice>> = callbackFlow {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context?, intent: Intent?) {
                if (intent?.action == WifiManager.SCAN_RESULTS_AVAILABLE_ACTION) {
                    trySend(readCurrentDevices())
                }
            }
        }

        val filter = IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            context.registerReceiver(receiver, filter)
        }

        val scanJob = launch {
            trySend(readCurrentDevices())
            while (true) {
                triggerScan()
                delay(15_000)
                trySend(readCurrentDevices())
            }
        }

        awaitClose {
            scanJob.cancel()
            context.unregisterReceiver(receiver)
        }
    }

    fun triggerScan(): Boolean = try {
        @Suppress("DEPRECATION")
        wifiManager.startScan()
    } catch (error: Exception) {
        Log.w(TAG, "WiFi scan request failed", error)
        false
    }

    private fun readCurrentDevices(): List<SignalDevice> {
        val scanDevices = try {
            @Suppress("DEPRECATION")
            wifiManager.scanResults.orEmpty().map { result ->
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
        } catch (error: SecurityException) {
            Log.w(TAG, "Missing permission for WiFi scan results", error)
            emptyList()
        } catch (error: Exception) {
            Log.w(TAG, "Unable to read WiFi scan results", error)
            emptyList()
        }

        return if (scanDevices.isNotEmpty()) {
            scanDevices
        } else {
            currentConnectionDevice()?.let { listOf(it) }.orEmpty()
        }
    }

    private fun currentConnectionDevice(): SignalDevice? = try {
        @Suppress("DEPRECATION")
        val info = wifiManager.connectionInfo ?: return null
        val ssid = info.ssid?.trim('"')?.takeIf { it.isNotBlank() && it != "<unknown ssid>" } ?: return null
        val bssid = info.bssid?.takeIf { it.isNotBlank() && it != "02:00:00:00:00:00" } ?: "connected"
        val (manufacturer, deviceClass, threat) = DeviceClassifier.classifyWifi(ssid, bssid, "Current WiFi connection")
        SignalDevice(
            id = "wifi_$bssid",
            name = ssid,
            address = bssid,
            signalType = SignalType.WIFI,
            signalStrength = info.rssi,
            frequency = info.frequency.toLong() * 1000,
            manufacturer = manufacturer,
            deviceClass = deviceClass,
            isEncrypted = true,
            channel = frequencyToChannel(info.frequency),
            threatLevel = threat,
            notes = "Current WiFi connection"
        )
    } catch (error: SecurityException) {
        Log.w(TAG, "Missing permission for current WiFi connection", error)
        null
    } catch (error: Exception) {
        Log.w(TAG, "Unable to read current WiFi connection", error)
        null
    }

    private fun frequencyToChannel(freq: Int): Int = when {
        freq in 2412..2484 -> (freq - 2412) / 5 + 1
        freq in 5180..5825 -> (freq - 5000) / 5
        else -> 0
    }

    private companion object {
        const val TAG = "WifiScanner"
    }
}
