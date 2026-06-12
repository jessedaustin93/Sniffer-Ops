package com.snifferops.service

import android.app.*
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.snifferops.MainActivity
import com.snifferops.R
import com.snifferops.data.SignalDetectionStore
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalType
import com.snifferops.model.ThreatLevel
import com.snifferops.scanner.BluetoothScanner
import com.snifferops.scanner.CellularScanner
import com.snifferops.scanner.WifiScanner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch

class ScannerService : Service() {

    companion object {
        const val CHANNEL_ID = "scanner_service_channel"
        const val NOTIFICATION_ID = 1001
        const val ACTION_START = "com.snifferops.START_SCAN"
        const val ACTION_STOP = "com.snifferops.STOP_SCAN"
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var scanJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                scanJob?.cancel()
                scanJob = null
                stopSelf()
            }
            else -> {
                startForeground(NOTIFICATION_ID, buildNotification("Recording signals and phone GPS..."))
                startScanning()
            }
        }
        return START_STICKY
    }

    private fun startScanning() {
        if (scanJob?.isActive == true) return
        scanJob = serviceScope.launch {
            val store = SignalDetectionStore(applicationContext)
            val wifi = WifiScanner(applicationContext)
            val bluetooth = BluetoothScanner(applicationContext)
            val cellular = CellularScanner(applicationContext)

            launch {
                wifi.scan().catch { }.collect { store.record(it) }
            }
            launch {
                bluetooth.scanClassic().catch { }.collect { store.record(it) }
            }
            launch {
                bluetooth.scanBle().catch { }.collect { store.record(it) }
            }
            launch {
                cellular.scan().catch { }.collect { towers ->
                    store.record(towers.map { tower ->
                        SignalDevice(
                            id = "cell_${tower.technology}_${tower.cid}_${tower.frequency}",
                            name = tower.carrier.ifBlank { "${tower.technology} cell tower" },
                            address = "CID ${tower.cid}",
                            signalType = SignalType.CELLULAR,
                            signalStrength = tower.signalStrength,
                            frequency = tower.frequency,
                            deviceClass = "${tower.technology} cell tower",
                            threatLevel = ThreatLevel.UNKNOWN,
                            notes = "MCC ${tower.mcc}; MNC ${tower.mnc}; LAC ${tower.lac}",
                            firstSeen = tower.timestamp,
                            lastSeen = tower.timestamp
                        )
                    })
                }
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scanJob?.cancel()
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun buildNotification(text: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("SnifferOps")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_search)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Scanner Service",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "SnifferOps background scanner"
        }
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
    }
}
