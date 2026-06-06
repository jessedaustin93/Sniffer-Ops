package com.snifferops.model

data class AwarenessProfile(
    val key: String,
    val name: String,
    val type: SignalType,
    val deviceClass: String,
    val threatLevel: ThreatLevel,
    val seenCount: Int,
    val nodeCount: Int,
    val lastSeen: Long,
    val latestEvent: String,
    val latitude: Double = 0.0,
    val longitude: Double = 0.0,
    val source: String = "local"
) {
    val status: AwarenessStatus
        get() = when {
            threatLevel == ThreatLevel.ALERT || threatLevel == ThreatLevel.SUSPICIOUS -> AwarenessStatus.WATCH
            seenCount <= 1 -> AwarenessStatus.ONE_OFF
            latestEvent.contains("jump", ignoreCase = true) ||
                latestEvent.contains("changed", ignoreCase = true) ||
                latestEvent.contains("again", ignoreCase = true) ||
                latestEvent.contains("new scan location", ignoreCase = true) -> AwarenessStatus.WATCH
            seenCount >= 3 -> AwarenessStatus.NORMAL
            else -> AwarenessStatus.LEARNING
        }
}

enum class AwarenessStatus {
    NORMAL, LEARNING, ONE_OFF, WATCH
}

data class AwarenessOverview(
    val total: Int = 0,
    val normal: Int = 0,
    val oneOff: Int = 0,
    val watch: Int = 0,
    val scanSpots: Int = 0,
    val latest: AwarenessProfile? = null
)

fun List<AwarenessProfile>.overview(): AwarenessOverview {
    val gpsSpots = mapNotNull { profile ->
        if (profile.latitude != 0.0 || profile.longitude != 0.0) {
            "%.4f,%.4f".format(profile.latitude, profile.longitude)
        } else {
            null
        }
    }.toSet().size
    return AwarenessOverview(
        total = size,
        normal = count { it.status == AwarenessStatus.NORMAL },
        oneOff = count { it.status == AwarenessStatus.ONE_OFF },
        watch = count { it.status == AwarenessStatus.WATCH },
        scanSpots = gpsSpots,
        latest = maxByOrNull { it.lastSeen }
    )
}
