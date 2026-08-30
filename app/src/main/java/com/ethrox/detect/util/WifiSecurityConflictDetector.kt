package com.ethrox.detect.util

import com.ethrox.detect.model.SignalDevice
import com.ethrox.detect.model.ThreatLevel

/**
 * Detects an in-scan security downgrade collision: an open BSSID advertising
 * the exact same visible SSID as a separately observed secured BSSID.  A BSSID
 * difference alone is deliberately not suspicious because it is normal for
 * mesh and multi-AP networks.
 */
object WifiSecurityConflictDetector {
    fun annotate(devices: List<SignalDevice>): List<SignalDevice> {
        val securedSsids = devices
            .filter { it.hasVisibleSsid() && it.isSecuredWifi() }
            .groupBy { it.normalizedSsid() }

        return devices.map { device ->
            val ssid = device.normalizedSsid()
            val securedPeers = securedSsids[ssid].orEmpty()
            val hasDifferentSecuredBssid = device.hasVisibleSsid() &&
                !device.isSecuredWifi() &&
                securedPeers.any { it.address.isNotBlank() && it.address != device.address }

            if (!hasDifferentSecuredBssid) return@map device

            val evidence = "Security mismatch: this BSSID advertises open Wi-Fi while " +
                "another currently visible BSSID advertises secured Wi-Fi for SSID '${device.name}'."
            device.copy(
                deviceClass = "Possible Wi-Fi security downgrade / evil-twin candidate",
                threatLevel = maxThreat(device.threatLevel, ThreatLevel.SUSPICIOUS),
                notes = listOf(device.notes, evidence).filter { it.isNotBlank() }.joinToString("; ")
            )
        }
    }

    private fun SignalDevice.normalizedSsid(): String = name.trim().lowercase()

    private fun SignalDevice.hasVisibleSsid(): Boolean =
        normalizedSsid().isNotBlank() && normalizedSsid() != "<hidden>"

    private fun SignalDevice.isSecuredWifi(): Boolean {
        val capabilities = notes.uppercase()
        return isEncrypted || listOf("WPA", "WEP", "RSN", "SAE", "EAP").any(capabilities::contains)
    }

    private fun maxThreat(first: ThreatLevel, second: ThreatLevel): ThreatLevel =
        if (first.ordinal >= second.ordinal) first else second
}
