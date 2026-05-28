package com.snifferops.scanner

import android.app.Activity
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.*
import android.os.Bundle
import com.snifferops.model.NfcTag
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

class NfcScanner(private val activity: Activity) {

    private val nfcAdapter: NfcAdapter? = NfcAdapter.getDefaultAdapter(activity)
    private val _lastTag = MutableStateFlow<NfcTag?>(null)
    val lastTag: StateFlow<NfcTag?> = _lastTag
    val isSupported: Boolean get() = nfcAdapter != null
    val isEnabled: Boolean get() = nfcAdapter?.isEnabled == true

    fun enableForegroundDispatch() {
        if (!isEnabled) return
        nfcAdapter?.enableReaderMode(
            activity,
            { tag -> processTag(tag) },
            NfcAdapter.FLAG_READER_NFC_A or
                    NfcAdapter.FLAG_READER_NFC_B or
                    NfcAdapter.FLAG_READER_NFC_F or
                    NfcAdapter.FLAG_READER_NFC_V or
                    NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,
            Bundle()
        )
    }

    fun disableForegroundDispatch() {
        nfcAdapter?.disableReaderMode(activity)
    }

    private fun processTag(tag: Tag) {
        val id = tag.id?.joinToString(":") { "%02X".format(it) } ?: "Unknown"
        val techList = tag.techList?.toList() ?: emptyList()
        val simpleTechs = techList.map { it.substringAfterLast('.') }

        val tagType = when {
            techList.any { it.contains("MifareClassic") } -> "MIFARE Classic"
            techList.any { it.contains("MifareUltralight") } -> "MIFARE Ultralight"
            techList.any { it.contains("Ndef") } -> "NDEF"
            techList.any { it.contains("IsoDep") } -> "ISO-DEP (Payment/ID)"
            techList.any { it.contains("NfcV") } -> "NFC-V (ISO 15693)"
            techList.any { it.contains("NfcF") } -> "NFC-F (FeliCa)"
            else -> "NFC Tag"
        }

        val data = readNdefData(tag) ?: ""

        _lastTag.value = NfcTag(
            id = id,
            technologies = simpleTechs,
            type = tagType,
            data = data
        )
    }

    private fun readNdefData(tag: Tag): String? = try {
        val ndef = Ndef.get(tag) ?: return null
        ndef.connect()
        val message = ndef.ndefMessage
        ndef.close()
        message?.records?.firstOrNull()?.let { record ->
            String(record.payload).drop(3)  // Skip language code prefix
        }
    } catch (_: Exception) { null }
}
