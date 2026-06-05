package com.snifferops

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.snifferops.model.NfcTag
import com.snifferops.scanner.RtlSdrScanner
import com.snifferops.ui.SnifferOpsNavHost
import com.snifferops.ui.theme.SnifferOpsTheme
import com.snifferops.viewmodel.DashboardViewModel

class MainActivity : ComponentActivity() {

    private val viewModel: DashboardViewModel by viewModels()

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        if (results.values.all { it }) {
            viewModel.startAllScans()
        } else {
            // Start scans with whatever permissions we have
            viewModel.startAllScans()
        }
    }

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val device: UsbDevice? = if (android.os.Build.VERSION.SDK_INT >= 33) {
                intent?.getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent?.getParcelableExtra(UsbManager.EXTRA_DEVICE)
            }
            when (intent?.action) {
                RtlSdrScanner.ACTION_USB_PERMISSION -> viewModel.onUsbPermissionResult()
                UsbManager.ACTION_USB_DEVICE_ATTACHED -> device?.let { viewModel.onUsbDeviceAttached(it) }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> device?.let { viewModel.onUsbDeviceDetached(it) }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Register USB receiver
        val usbFilter = IntentFilter().apply {
            addAction(RtlSdrScanner.ACTION_USB_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(usbReceiver, usbFilter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(usbReceiver, usbFilter)
        }
        viewModel.requestSdrPermissionIfConnected()

        // Request permissions
        requestPermissions()

        setContent {
            SnifferOpsTheme {
                val state = viewModel.state.collectAsStateWithLifecycle()
                SnifferOpsNavHost(
                    state = state.value,
                    viewModel = viewModel
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        enableNfcForegroundDispatch()
    }

    override fun onPause() {
        super.onPause()
        disableNfcForegroundDispatch()
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(usbReceiver)
    }

    // NFC tag dispatch (handled via NfcAdapter.ReaderMode in NfcScanner)
    private var nfcAdapter: NfcAdapter? = null

    private fun enableNfcForegroundDispatch() {
        nfcAdapter = NfcAdapter.getDefaultAdapter(this)
        nfcAdapter?.enableReaderMode(
            this,
            { tag: Tag ->
                val id = tag.id?.joinToString(":") { "%02X".format(it) } ?: "Unknown"
                val techs = tag.techList?.map { it.substringAfterLast('.') } ?: emptyList()
                val nfcTag = NfcTag(id = id, technologies = techs, type = techs.firstOrNull() ?: "NFC")
                runOnUiThread { viewModel.onNfcTagDetected(nfcTag) }
            },
            NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_NFC_B or
                    NfcAdapter.FLAG_READER_NFC_F or NfcAdapter.FLAG_READER_NFC_V,
            Bundle()
        )
    }

    private fun disableNfcForegroundDispatch() {
        nfcAdapter?.disableReaderMode(this)
    }

    private fun requestPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.BLUETOOTH_CONNECT,
            Manifest.permission.READ_PHONE_STATE,
            Manifest.permission.POST_NOTIFICATIONS,
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            permissions += Manifest.permission.BLUETOOTH_SCAN
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions += Manifest.permission.NEARBY_WIFI_DEVICES
        }
        permissionLauncher.launch(permissions.toTypedArray())
    }
}
