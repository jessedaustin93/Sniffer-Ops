package com.ethrox.detect.util

import com.ethrox.detect.model.SignalDevice
import com.ethrox.detect.model.ThreatLevel

data class SignalDeviceGroup(
    val key: String,
    val primary: SignalDevice,
    val devices: List<SignalDevice>
) {
    val count: Int get() = devices.size
    val title: String
        get() = primary.name.ifBlank { primary.deviceClass.ifBlank { primary.signalType.name } }
    val typeLabel: String
        get() = primary.deviceClass.ifBlank { primary.signalType.name }
    val strongestSignal: Int
        get() = devices.maxOfOrNull { it.signalStrength } ?: primary.signalStrength
}

fun List<SignalDevice>.groupSignalDevices(): List<SignalDeviceGroup> =
    groupBy { it.signalGroupKey() }
        .values
        .map { group ->
            val primary = group.maxWithOrNull(
                compareBy<SignalDevice> { it.localAlertRank() }
                    .thenBy { it.signalStrength }
                    .thenBy { it.lastSeen }
            ) ?: group.first()
            SignalDeviceGroup(
                key = primary.signalGroupKey(),
                primary = primary,
                devices = group.sortedForLocalDisplay()
            )
        }
        .sortedWith(
            compareByDescending<SignalDeviceGroup> { it.primary.localAlertRank() }
                .thenByDescending { it.strongestSignal }
                .thenByDescending { it.primary.lastSeen }
        )

fun List<SignalDevice>.sortedForLocalDisplay(): List<SignalDevice> =
    sortedWith(
        compareByDescending<SignalDevice> { it.localAlertRank() }
            .thenByDescending { it.signalStrength }
            .thenByDescending { it.lastSeen }
    )

fun SignalDevice.localAlertRank(): Int {
    val text = listOf(name, signalType.name, deviceClass, manufacturer, notes)
        .joinToString(" ")
        .lowercase()
    val hostileInfrastructure = Regex("flock|alpr|lpr|license\\s*plate|plate\\s*reader|traffic\\s*reader|traffic\\s*camera|speed\\s*camera|red\\s*light")
    val activeThreat = Regex("evil\\s*twin|pineapple|deauther|marauder|pwnagotchi|badusb|credential|password|phish|skimmer|sniffer|rogue\\s*ap")
    val tracker = Regex("airtag|find\\s*my|smarttag|tile|chipolo|tracker|unknown\\s*ble|ble\\s*tag")
    val surveillance = Regex("surveillance|camera|cctv|verkada|avigilon|hikvision|dahua|axis|vigilant|genetec|motorola")

    return when {
        threatLevel == ThreatLevel.ALERT || activeThreat.containsMatchIn(text) -> 400
        hostileInfrastructure.containsMatchIn(text) -> 350
        threatLevel == ThreatLevel.SUSPICIOUS || surveillance.containsMatchIn(text) -> 300
        tracker.containsMatchIn(text) -> 220
        threatLevel == ThreatLevel.UNKNOWN -> 120
        else -> 0
    }
}

private fun SignalDevice.signalGroupKey(): String {
    val type = deviceClass.ifBlank { signalType.name }.lowercase()
    val nameKey = name.trim().lowercase()
    val vendorKey = manufacturer.takeUnless { it == "Unknown" }.orEmpty().lowercase()
    val flockLike = type.contains("flock") || nameKey.contains("flock") || vendorKey.contains("flock")
    if (flockLike) return "${signalType.name}:flock:${vendorKey.ifBlank { "unknown" }}"

    val genericType = type in setOf(
        "bluetooth device",
        "wifi wireless device",
        "wifi access point",
        "rf signal",
        signalType.name.lowercase()
    )
    val usableName = nameKey.isNotBlank() &&
        nameKey !in setOf("unknown", "unknown ble", "<hidden>", "hidden wifi")

    return when {
        signalType.name == "WIFI" && usableName -> "${signalType.name}:$nameKey"
        usableName -> "${signalType.name}:$type:$nameKey"
        !genericType && vendorKey.isNotBlank() -> "${signalType.name}:$type:$vendorKey"
        !genericType -> "${signalType.name}:$type"
        else -> id
    }
}
