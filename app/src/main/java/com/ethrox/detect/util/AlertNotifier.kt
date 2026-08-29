package com.ethrox.detect.util

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.ethrox.detect.MainActivity
import com.ethrox.detect.model.SignalDevice
import com.ethrox.detect.model.ThreatLevel

/**
 * Posts an Android notification the first time a device crosses into
 * ALERT/SUSPICIOUS, using the "scanner_alerts" channel that
 * EthroxDetectApp already creates (previously unused). Tracks already-
 * notified ids so a still-live alert doesn't re-notify every scan tick.
 */
class AlertNotifier(private val context: Context) {

    companion object {
        private const val CHANNEL_ID = "scanner_alerts"
    }

    private val notifiedIds = HashSet<String>()

    /** Call with the current alert-relevant devices each time state updates. */
    fun onAlertDevicesChanged(devices: List<SignalDevice>) {
        val currentIds = devices.mapTo(HashSet()) { it.id }

        // Clear tracking for devices that are no longer alert-relevant so a
        // future re-appearance notifies again instead of staying suppressed.
        notifiedIds.retainAll(currentIds)

        for (device in devices) {
            if (device.threatLevel != ThreatLevel.ALERT && device.threatLevel != ThreatLevel.SUSPICIOUS) {
                continue
            }
            if (!notifiedIds.add(device.id)) {
                continue  // already notified for this device while it's been live
            }
            postNotification(device)
        }
    }

    private fun postNotification(device: SignalDevice) {
        if (ActivityCompat.checkSelfPermission(
                context, Manifest.permission.POST_NOTIFICATIONS
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        val openIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            context, device.id.hashCode(), openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val title = if (device.threatLevel == ThreatLevel.ALERT) {
            "Ethrox Detect: Alert"
        } else {
            "Ethrox Detect: Suspicious signal"
        }
        val label = device.name.ifBlank { device.address }.ifBlank { device.signalType.name }

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(title)
            .setContentText(label)
            .setStyle(NotificationCompat.BigTextStyle().bigText("$label — ${device.deviceClass.ifBlank { device.signalType.name }}"))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        NotificationManagerCompat.from(context).notify(device.id.hashCode(), notification)
    }
}
