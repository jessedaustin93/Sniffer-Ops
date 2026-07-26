package com.ethrox.detect

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import com.ethrox.detect.util.SignatureEngine

class EthroxDetectApp : Application() {

    override fun onCreate() {
        super.onCreate()
        SignatureEngine.initialize(this)
        createNotificationChannels()
    }

    private fun createNotificationChannels() {
        val channels = listOf(
            NotificationChannel(
                "scanner_alerts",
                "Signal Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply { description = "Alerts for suspicious or notable signals" },
            NotificationChannel(
                "scanner_service_channel",
                "Scanner Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply { description = "Background scanning service" }
        )
        getSystemService(NotificationManager::class.java)?.run {
            channels.forEach { createNotificationChannel(it) }
        }
    }
}
