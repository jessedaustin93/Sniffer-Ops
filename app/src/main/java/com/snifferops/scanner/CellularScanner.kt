package com.snifferops.scanner

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.telephony.*
import com.snifferops.model.CellTower
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

@SuppressLint("MissingPermission")
class CellularScanner(private val context: Context) {

    private val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager

    fun scan(): Flow<List<CellTower>> = callbackFlow {
        val callback = object : PhoneStateListener() {
            @Deprecated("Deprecated in Java")
            override fun onCellInfoChanged(cellInfo: MutableList<CellInfo>?) {
                trySend(parseCellInfo(cellInfo ?: emptyList()))
            }
        }

        @Suppress("DEPRECATION")
        telephonyManager.listen(callback, PhoneStateListener.LISTEN_CELL_INFO)

        // Send current state immediately
        val current = try { telephonyManager.allCellInfo ?: emptyList() } catch (_: Exception) { emptyList() }
        trySend(parseCellInfo(current))

        awaitClose {
            @Suppress("DEPRECATION")
            telephonyManager.listen(callback, PhoneStateListener.LISTEN_NONE)
        }
    }

    private fun parseCellInfo(cellInfoList: List<CellInfo>): List<CellTower> {
        return cellInfoList.mapNotNull { info ->
            try {
                when (info) {
                    is CellInfoLte -> {
                        val id = info.cellIdentity
                        val signal = info.cellSignalStrength
                        CellTower(
                            mcc = id.mccString?.toIntOrNull() ?: 0,
                            mnc = id.mncString?.toIntOrNull() ?: 0,
                            lac = if (Build.VERSION.SDK_INT >= 28) id.tac else 0,
                            cid = id.ci,
                            signalStrength = signal.dbm,
                            technology = "LTE",
                            carrier = telephonyManager.networkOperatorName ?: "",
                            frequency = if (Build.VERSION.SDK_INT >= 24) id.earfcn.toLong() else 0L
                        )
                    }
                    is CellInfoGsm -> {
                        val id = info.cellIdentity
                        val signal = info.cellSignalStrength
                        CellTower(
                            mcc = id.mccString?.toIntOrNull() ?: 0,
                            mnc = id.mncString?.toIntOrNull() ?: 0,
                            lac = id.lac,
                            cid = id.cid,
                            signalStrength = signal.dbm,
                            technology = "GSM",
                            carrier = telephonyManager.networkOperatorName ?: ""
                        )
                    }
                    is CellInfoWcdma -> {
                        val id = info.cellIdentity
                        val signal = info.cellSignalStrength
                        CellTower(
                            mcc = id.mccString?.toIntOrNull() ?: 0,
                            mnc = id.mncString?.toIntOrNull() ?: 0,
                            lac = id.lac,
                            cid = id.cid,
                            signalStrength = signal.dbm,
                            technology = "WCDMA/UMTS",
                            carrier = telephonyManager.networkOperatorName ?: ""
                        )
                    }
                    is CellInfoNr -> {
                        if (Build.VERSION.SDK_INT >= 29) {
                            val id = info.cellIdentity as CellIdentityNr
                            val signal = info.cellSignalStrength as CellSignalStrengthNr
                            CellTower(
                                mcc = id.mccString?.toIntOrNull() ?: 0,
                                mnc = id.mncString?.toIntOrNull() ?: 0,
                                lac = 0,
                                cid = id.nci.toInt(),
                                signalStrength = signal.dbm,
                                technology = "5G NR",
                                carrier = telephonyManager.networkOperatorName ?: ""
                            )
                        } else null
                    }
                    else -> null
                }
            } catch (_: Exception) { null }
        }
    }
}
