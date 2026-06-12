package com.snifferops.sync

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
import android.location.LocationManager
import android.util.Log

data class NodeLocation(
    val latitude: Double,
    val longitude: Double,
    val accuracyMeters: Float,
    val provider: String,
    val timestamp: Long
)

class NodeLocationProvider(private val context: Context) {

    private val locationManager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager

    @SuppressLint("MissingPermission")
    fun bestLastKnownLocation(): NodeLocation? = try {
        val candidates = locationManager.allProviders.mapNotNull { provider ->
            runCatching { locationManager.getLastKnownLocation(provider) }.getOrNull()
        }
        candidates
            .filter { it.latitude in -90.0..90.0 && it.longitude in -180.0..180.0 }
            .maxWithOrNull(compareBy<Location> { it.time }.thenBy { -it.accuracy })?.let { location ->
            NodeLocation(
                latitude = location.latitude,
                longitude = location.longitude,
                accuracyMeters = location.accuracy,
                provider = location.provider ?: "unknown",
                timestamp = location.time
            )
        }
    } catch (error: SecurityException) {
        Log.w(TAG, "Location permission is missing for awareness sync", error)
        null
    } catch (error: Exception) {
        Log.w(TAG, "Unable to read node location for awareness sync", error)
        null
    }

    private companion object {
        const val TAG = "NodeLocationProvider"
    }
}
