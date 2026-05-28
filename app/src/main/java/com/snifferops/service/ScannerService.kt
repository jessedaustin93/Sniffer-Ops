package com.snifferops.service

import android.app.*
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.snifferops.MainActivity
import com.snifferops.R

class ScannerService : Service() {

    companion object {
        const val CHANNEL_ID = "scanner_service_channel"
        const val NOTIFICATION_ID = 1001
        const val ACTION_START = "com.snifferops.START_SCAN"
        const val ACTION_STOP = "com.snifferops.STOP_SCAN"
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startForeground(NOTIFICATION_ID, buildNotification("Scanning for signals..."))
            ACTION_STOP -> stopSelf()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

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
