package com.ethrox.detect.scanner

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Handler
import android.os.Looper
import com.ethrox.detect.model.SignalDevice
import com.ethrox.detect.model.SignalType
import com.ethrox.detect.util.DeviceClassifier
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

@SuppressLint("MissingPermission")
class BluetoothScanner(private val context: Context) {

    private val btManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val btAdapter: BluetoothAdapter? = btManager.adapter
    private val mainHandler = Handler(Looper.getMainLooper())

    fun scanClassic(): Flow<List<SignalDevice>> = callbackFlow {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context?, intent: Intent?) {
                when (intent?.action) {
                    BluetoothDevice.ACTION_FOUND -> {
                        val device: BluetoothDevice = if (android.os.Build.VERSION.SDK_INT >= 33) {
                            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)!!
                        } else {
                            @Suppress("DEPRECATION")
                            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)!!
                        }
                        val rssi = intent.getShortExtra(BluetoothDevice.EXTRA_RSSI, Short.MIN_VALUE).toInt()
                        val name = try { device.name ?: "Unknown" } catch (_: Exception) { "Unknown" }
                        val address = device.address ?: return
                        val (mfr, cls, threat) = DeviceClassifier.classifyBluetooth(name, address)

                        val sd = SignalDevice(
                            id = "bt_$address",
                            name = name,
                            address = address,
                            signalType = SignalType.BLUETOOTH,
                            signalStrength = rssi,
                            manufacturer = mfr,
                            deviceClass = cls,
                            threatLevel = threat
                        )
                        trySend(listOf(sd))
                    }
                    BluetoothAdapter.ACTION_DISCOVERY_FINISHED -> {
                        mainHandler.postDelayed({
                            runCatching { btAdapter?.startDiscovery() }
                        }, CLASSIC_DISCOVERY_RESTART_DELAY_MS)
                    }
                }
            }
        }

        val filter = IntentFilter().apply {
            addAction(BluetoothDevice.ACTION_FOUND)
            addAction(BluetoothAdapter.ACTION_DISCOVERY_FINISHED)
        }
        context.registerReceiver(receiver, filter)
        btAdapter?.startDiscovery()

        awaitClose {
            mainHandler.removeCallbacksAndMessages(null)
            btAdapter?.cancelDiscovery()
            context.unregisterReceiver(receiver)
        }
    }

    fun scanBle(): Flow<List<SignalDevice>> = callbackFlow {
        val scanner = btAdapter?.bluetoothLeScanner

        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                val device = result.device
                val name = try {
                    result.scanRecord?.deviceName ?: device.name ?: "Unknown BLE"
                } catch (_: Exception) { "Unknown BLE" }
                val address = device.address ?: return
                val (mfr, cls, threat) = DeviceClassifier.classifyBluetooth(name, address)
                val record = result.scanRecord
                val serviceUuids = record?.serviceUuids.orEmpty().joinToString(",") { it.uuid.toString() }
                val manufacturerData = record?.manufacturerSpecificData?.let { sparse ->
                    buildList {
                        for (i in 0 until sparse.size()) {
                            val key = sparse.keyAt(i)
                            val bytes = sparse.valueAt(i)
                            add("$key:${bytes.toHex()}")
                        }
                    }.joinToString(",")
                }.orEmpty()
                val serviceData = record?.serviceData?.entries.orEmpty().joinToString(",") { entry ->
                    "${entry.key.uuid}:${entry.value.toHex()}"
                }
                val txPower = record?.txPowerLevel?.takeIf { it != Int.MIN_VALUE }
                val notes = buildList {
                    if (serviceUuids.isNotBlank()) add("serviceUuids=$serviceUuids")
                    if (manufacturerData.isNotBlank()) add("manufacturerData=$manufacturerData")
                    if (serviceData.isNotBlank()) add("serviceData=$serviceData")
                    if (txPower != null) add("txPower=$txPower")
                    add("connectable=${result.isConnectable}")
                    if (record?.deviceName != null) add("advertisedName=${record.deviceName}")
                }.joinToString("; ")

                val sd = SignalDevice(
                    id = "ble_$address",
                    name = name,
                    address = address,
                    signalType = SignalType.BLE,
                    signalStrength = result.rssi,
                    manufacturer = mfr,
                    deviceClass = cls,
                    threatLevel = threat,
                    notes = notes
                )
                trySend(listOf(sd))
            }

            override fun onScanFailed(errorCode: Int) {}
        }

        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_BALANCED)
            .build()

        scanner?.startScan(null, settings, callback)

        awaitClose { scanner?.stopScan(callback) }
    }

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

    private companion object {
        const val CLASSIC_DISCOVERY_RESTART_DELAY_MS = 10_000L
    }
}
