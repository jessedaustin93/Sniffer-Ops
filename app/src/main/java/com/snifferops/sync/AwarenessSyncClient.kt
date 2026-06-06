package com.snifferops.sync

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.util.Log
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalType
import com.snifferops.model.ThreatLevel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class AwarenessSyncResult(
    val merged: Int,
    val totalSignals: Int,
    val updatedDevices: List<SignalDevice>
)

class AwarenessSyncClient(private val context: Context) {

    private val locationProvider = NodeLocationProvider(context)

    suspend fun sync(host: String, port: Int, devices: List<SignalDevice>): AwarenessSyncResult =
        withContext(Dispatchers.IO) {
            val cleanHost = host.trim()
            require(cleanHost.isNotBlank()) { "Windows sync host is blank" }

            val url = URL("http://$cleanHost:$port/snifferops/sync")
            val connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 2500
                readTimeout = 4000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }

            val snapshot = buildSnapshot(devices)
            connection.outputStream.use { output ->
                output.write(snapshot.toString().toByteArray(Charsets.UTF_8))
            }

            val status = connection.responseCode
            val body = if (status in 200..299) {
                connection.inputStream.bufferedReader().use { it.readText() }
            } else {
                val error = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                throw IllegalStateException("Windows sync returned HTTP $status $error")
            }

            parseResult(JSONObject(body))
        }

    private fun buildSnapshot(devices: List<SignalDevice>): JSONObject {
        val location = locationProvider.bestLastKnownLocation()
        return JSONObject().apply {
            put("schema", 1)
            put("nodeId", nodeId())
            put("nodeName", "${Build.MANUFACTURER} ${Build.MODEL}".trim())
            put("capturedAt", System.currentTimeMillis())
            put("location", JSONObject().apply {
                if (location != null) {
                    put("latitude", location.latitude)
                    put("longitude", location.longitude)
                    put("accuracyMeters", location.accuracyMeters.toDouble())
                    put("provider", location.provider)
                    put("timestamp", location.timestamp)
                }
            })
            put("signals", JSONArray().apply {
                devices.forEach { device -> put(device.toJson()) }
            })
        }
    }

    private fun SignalDevice.toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("name", name)
        put("address", address)
        put("type", signalType.name)
        put("signalStrength", signalStrength)
        put("frequencyHz", frequency)
        put("manufacturer", manufacturer)
        put("deviceClass", deviceClass)
        put("isEncrypted", isEncrypted)
        put("channel", channel)
        if (latitude != 0.0 || longitude != 0.0) {
            put("latitude", latitude)
            put("longitude", longitude)
        }
        put("threatLevel", threatLevel.name)
        put("notes", notes)
        put("firstSeen", firstSeen)
        put("lastSeen", lastSeen)
        put("seenCount", seenCount)
    }

    private fun parseResult(json: JSONObject): AwarenessSyncResult {
        val signals = json.optJSONArray("signals") ?: JSONArray()
        val devices = buildList {
            for (i in 0 until signals.length()) {
                val item = signals.optJSONObject(i) ?: continue
                toSignalDevice(item)?.let { add(it) }
            }
        }
        return AwarenessSyncResult(
            merged = json.optInt("merged", 0),
            totalSignals = json.optInt("totalSignals", devices.size),
            updatedDevices = devices
        )
    }

    private fun toSignalDevice(item: JSONObject): SignalDevice? = try {
        val key = item.optString("key", item.optString("address", item.optString("name", "")))
        val type = runCatching { SignalType.valueOf(item.optString("type", "UNKNOWN")) }.getOrDefault(SignalType.UNKNOWN)
        val threat = runCatching { ThreatLevel.valueOf(item.optString("threatLevel", "UNKNOWN")) }.getOrDefault(ThreatLevel.UNKNOWN)
        SignalDevice(
            id = "awareness_${key.hashCode()}",
            name = item.optString("name", type.name),
            address = item.optString("address", key),
            signalType = type,
            signalStrength = item.optInt("signalStrength", item.optInt("strongestSignal", 0)),
            frequency = item.optLong("frequencyHz", 0L),
            manufacturer = item.optString("manufacturer", ""),
            deviceClass = item.optString("deviceClass", "Synced awareness signal"),
            channel = item.optInt("channel", 0),
            latitude = item.optDouble("estimatedLatitude", 0.0),
            longitude = item.optDouble("estimatedLongitude", 0.0),
            threatLevel = threat,
            notes = "Synced from Windows awareness log; seen ${item.optInt("seenCount", 0)}x from ${item.optInt("nodeCount", 0)} node(s)",
            firstSeen = parseTime(item.optString("firstSeen")),
            lastSeen = parseTime(item.optString("lastSeen")),
            seenCount = item.optInt("seenCount", 1)
        )
    } catch (error: Exception) {
        Log.w(TAG, "Skipping malformed awareness signal", error)
        null
    }

    private fun nodeId(): String =
        Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
            ?: "${Build.MANUFACTURER}-${Build.MODEL}"

    private fun parseTime(value: String): Long =
        runCatching { java.time.Instant.parse(value).toEpochMilli() }.getOrDefault(System.currentTimeMillis())

    private companion object {
        const val TAG = "AwarenessSyncClient"
    }
}
