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
            threatLevel == ThreatLevel.ALERT -> AwarenessStatus.ALERT
            threatLevel == ThreatLevel.SUSPICIOUS && hasMovementEvent -> AwarenessStatus.ALERT
            threatLevel == ThreatLevel.SUSPICIOUS -> AwarenessStatus.WATCH
            threatLevel == ThreatLevel.UNKNOWN && seenCount < NORMAL_BASELINE_COUNT -> AwarenessStatus.NOTICED
            seenCount <= 1 -> AwarenessStatus.ONE_OFF
            seenCount >= NORMAL_BASELINE_COUNT -> AwarenessStatus.NORMAL
            else -> AwarenessStatus.LEARNING
        }

    private val hasMovementEvent: Boolean
        get() = latestEvent.contains("new scan location", ignoreCase = true) ||
            latestEvent.contains("location_changed", ignoreCase = true) ||
            latestEvent.contains("also seen by", ignoreCase = true) ||
            latestEvent.contains("following", ignoreCase = true) ||
            latestEvent.contains("moved with", ignoreCase = true)
}

enum class AwarenessStatus {
    NORMAL, LEARNING, ONE_OFF, NOTICED, WATCH, ALERT
}

private const val NORMAL_BASELINE_COUNT = 5

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
        oneOff = count { it.status == AwarenessStatus.ONE_OFF || it.status == AwarenessStatus.NOTICED },
        watch = count { it.status == AwarenessStatus.WATCH || it.status == AwarenessStatus.ALERT },
        scanSpots = gpsSpots,
        latest = maxByOrNull { it.lastSeen }
    )
}
