package com.ethrox.detect

import android.Manifest
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
import com.ethrox.detect.model.NfcTag
import com.ethrox.detect.ui.EthroxDetectNavHost
import com.ethrox.detect.ui.theme.EthroxDetectTheme
import com.ethrox.detect.viewmodel.DashboardViewModel

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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Request permissions
        requestPermissions()

        setContent {
            EthroxDetectTheme {
                val state = viewModel.state.collectAsStateWithLifecycle()
                EthroxDetectNavHost(
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
