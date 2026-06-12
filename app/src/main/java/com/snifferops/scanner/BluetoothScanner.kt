package com.snifferops.scanner

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
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalType
import com.snifferops.util.DeviceClassifier
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

@SuppressLint("MissingPermission")
class BluetoothScanner(private val context: Context) {

    private val btManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val btAdapter: BluetoothAdapter? = btManager.adapter

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
                        btAdapter?.startDiscovery()
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

                val sd = SignalDevice(
                    id = "ble_$address",
                    name = name,
                    address = address,
                    signalType = SignalType.BLE,
                    signalStrength = result.rssi,
                    manufacturer = mfr,
                    deviceClass = cls,
                    threatLevel = threat
                )
                trySend(listOf(sd))
            }

            override fun onScanFailed(errorCode: Int) {}
        }

        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()

        scanner?.startScan(null, settings, callback)

        awaitClose { scanner?.stopScan(callback) }
    }
}
