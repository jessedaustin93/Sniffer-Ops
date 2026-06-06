package com.snifferops.util

import com.snifferops.model.SignalDevice

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
            val primary = group.maxByOrNull { it.signalStrength } ?: group.first()
            SignalDeviceGroup(
                key = primary.signalGroupKey(),
                primary = primary,
                devices = group.sortedByDescending { it.signalStrength }
            )
        }
        .sortedByDescending { it.strongestSignal }

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
