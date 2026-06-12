package com.snifferops.data

import android.content.Context
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalSighting
import com.snifferops.sync.NodeLocationProvider
import java.util.concurrent.ConcurrentHashMap

class SignalDetectionStore(context: Context) {
    private val dao = AppDatabase.getInstance(context).signalDeviceDao()
    private val locationProvider = NodeLocationProvider(context)
    private val recordedAtById = ConcurrentHashMap<String, Long>()

    suspend fun record(devices: List<SignalDevice>) {
        if (devices.isEmpty()) return
        val now = System.currentTimeMillis()
        val location = locationProvider.bestLastKnownLocation()
        val profiles = ArrayList<SignalDevice>(devices.size)
        val sightings = ArrayList<SignalSighting>()
        val existingById = dao.getDevicesByIds(devices.map { it.id }.distinct()).associateBy { it.id }

        devices.forEach { incoming ->
            val existing = existingById[incoming.id]
            profiles += incoming.mergeWith(existing, now, location)
            val lastRecordedAt = recordedAtById[incoming.id] ?: existing?.lastSeen ?: 0L
            if (now - lastRecordedAt >= SIGHTING_INTERVAL_MS) {
                recordedAtById[incoming.id] = now
                sightings += SignalSighting(
                    deviceId = incoming.id,
                    capturedAt = now,
                    latitude = location?.latitude,
                    longitude = location?.longitude,
                    accuracyMeters = location?.accuracyMeters,
                    signalStrength = incoming.signalStrength
                )
            }
        }
        dao.storeDetectionBatch(profiles, sightings)
    }

    private fun SignalDevice.mergeWith(
        existing: SignalDevice?,
        now: Long,
        location: com.snifferops.sync.NodeLocation?
    ): SignalDevice = copy(
        name = name.ifBlank { existing?.name.orEmpty() },
        address = address.ifBlank { existing?.address.orEmpty() },
        frequency = frequency.takeIf { it != 0L } ?: existing?.frequency ?: 0L,
        manufacturer = manufacturer.ifBlank { existing?.manufacturer.orEmpty() },
        deviceClass = deviceClass.ifBlank { existing?.deviceClass.orEmpty() },
        channel = channel.takeIf { it != 0 } ?: existing?.channel ?: 0,
        latitude = location?.latitude ?: latitude.takeIf { it != 0.0 } ?: existing?.latitude ?: 0.0,
        longitude = location?.longitude ?: longitude.takeIf { it != 0.0 } ?: existing?.longitude ?: 0.0,
        notes = notes.ifBlank { existing?.notes.orEmpty() },
        firstSeen = existing?.firstSeen ?: firstSeen,
        lastSeen = now,
        seenCount = (existing?.seenCount ?: 0) + 1
    )

    private companion object {
        const val SIGHTING_INTERVAL_MS = 10_000L
    }
}
