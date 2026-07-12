package com.ethrox.detect.model

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import java.util.UUID

@Entity(
    tableName = "signal_sightings",
    indices = [Index("deviceId"), Index("capturedAt"), Index("syncedAt")]
)
data class SignalSighting(
    @PrimaryKey val id: String = UUID.randomUUID().toString(),
    val deviceId: String,
    val capturedAt: Long,
    val latitude: Double?,
    val longitude: Double?,
    val accuracyMeters: Float?,
    val signalStrength: Int,
    val syncedAt: Long? = null,
    val movementSessionId: String? = null,
    val speedMetersPerSecond: Float? = null,
    val bearingDegrees: Float? = null,
    val locationProvider: String? = null
)
