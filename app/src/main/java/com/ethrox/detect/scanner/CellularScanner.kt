package com.ethrox.detect.scanner

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.util.Log
import android.telephony.*
import com.ethrox.detect.model.CellTower
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch

@SuppressLint("MissingPermission")
class CellularScanner(private val context: Context) {

    private val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
    private val subscriptionManager =
        context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as SubscriptionManager

    fun scan(): Flow<List<CellTower>> = callbackFlow {
        val refreshJob = launch {
            while (true) {
                val managers = activeTelephonyManagers()
                val current = managers
                    .flatMap { manager -> readCurrentTowers(manager) }
                    .distinctBy(CellTower::identityKey)
                trySend(current)
                managers.forEach { manager ->
                    requestFreshCellInfo(manager) { towers ->
                        if (towers.isNotEmpty()) {
                            trySend(towers.distinctBy(CellTower::identityKey))
                        }
                    }
                }
                delay(REFRESH_INTERVAL_MS)
            }
        }

        awaitClose {
            refreshJob.cancel()
        }
    }

    private fun activeTelephonyManagers(): List<TelephonyManager> {
        val subscriptionIds = try {
            subscriptionManager.activeSubscriptionInfoList
                .orEmpty()
                .map { info -> info.subscriptionId }
                .filter(SubscriptionManager::isValidSubscriptionId)
                .distinct()
        } catch (error: Exception) {
            Log.w(TAG, "Unable to enumerate active cellular subscriptions", error)
            emptyList()
        }

        return if (subscriptionIds.isEmpty()) {
            listOf(telephonyManager)
        } else {
            subscriptionIds.map(telephonyManager::createForSubscriptionId)
        }
    }

    private fun readCurrentTowers(manager: TelephonyManager): List<CellTower> = try {
        parseCellInfo(manager, manager.allCellInfo.orEmpty())
    } catch (error: Exception) {
        Log.w(TAG, "Unable to read current cellular information", error)
        emptyList()
    }

    private fun requestFreshCellInfo(
        manager: TelephonyManager,
        onResult: (List<CellTower>) -> Unit
    ) {
        try {
            manager.requestCellInfoUpdate(
                context.mainExecutor,
                object : TelephonyManager.CellInfoCallback() {
                    override fun onCellInfo(cellInfo: MutableList<CellInfo>) {
                        onResult(parseCellInfo(manager, cellInfo))
                    }

                    override fun onError(errorCode: Int, detail: Throwable?) {
                        Log.d(TAG, "Cell information refresh unavailable: $errorCode", detail)
                    }
                }
            )
        } catch (error: Exception) {
            Log.d(TAG, "Cell information refresh request failed", error)
        }
    }

    private fun parseCellInfo(
        manager: TelephonyManager,
        cellInfoList: List<CellInfo>
    ): List<CellTower> {
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
                            carrier = manager.networkOperatorName ?: "",
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
                            carrier = manager.networkOperatorName ?: ""
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
                            carrier = manager.networkOperatorName ?: ""
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
                                carrier = manager.networkOperatorName ?: ""
                            )
                        } else null
                    }
                    else -> null
                }
            } catch (_: Exception) { null }
        }
    }

    private companion object {
        const val TAG = "CellularScanner"
        const val REFRESH_INTERVAL_MS = 15_000L
    }
}

private fun CellTower.identityKey(): String =
    "$technology|$mcc|$mnc|$lac|$cid|$frequency"
