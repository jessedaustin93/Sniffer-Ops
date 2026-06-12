package com.snifferops.sync

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.util.Log
import com.snifferops.model.AwarenessProfile
import com.snifferops.model.SdrSignal
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalSighting
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
    val updatedDevices: List<SignalDevice>,
    val profiles: List<AwarenessProfile>,
    val acknowledgedSightingIds: List<String> = emptyList()
)

data class WindowsSdrDeepScanResult(
    val scanId: String,
    val state: String,
    val message: String,
    val running: Boolean,
    val completed: Boolean,
    val sdrSignals: List<SdrSignal>,
    val awareness: AwarenessSyncResult
)

class AwarenessSyncClient(private val context: Context) {

    suspend fun healthCheck(host: String, port: Int): Boolean =
        withContext(Dispatchers.IO) {
            val cleanHost = host.trim()
            require(cleanHost.isNotBlank()) { "PC sync host is blank" }

            val url = URL("http://$cleanHost:$port/snifferops/health")
            val connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 2000
                readTimeout = 2500
            }
            runCatching {
                connection.responseCode in 200..299
            }.getOrDefault(false).also {
                connection.disconnect()
            }
        }

    suspend fun sync(
        host: String,
        port: Int,
        devices: List<SignalDevice>,
        sightings: List<SignalSighting>
    ): AwarenessSyncResult =
        withContext(Dispatchers.IO) {
            val cleanHost = host.trim()
            require(cleanHost.isNotBlank()) { "PC sync host is blank" }

            val url = URL("http://$cleanHost:$port/snifferops/sync")
            val connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 4000
                readTimeout = 12000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }

            val snapshot = buildSnapshot(devices, sightings)
            connection.outputStream.use { output ->
                output.write(snapshot.toString().toByteArray(Charsets.UTF_8))
            }

            val status = connection.responseCode
            val body = if (status in 200..299) {
                connection.inputStream.bufferedReader().use { it.readText() }
            } else {
                val error = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                throw IllegalStateException("PC sync returned HTTP $status $error")
            }

            parseResult(JSONObject(body))
        }

    suspend fun fetchAwareness(host: String, port: Int): AwarenessSyncResult =
        withContext(Dispatchers.IO) {
            val cleanHost = host.trim()
            require(cleanHost.isNotBlank()) { "PC sync host is blank" }

            val url = URL("http://$cleanHost:$port/snifferops/awareness")
            val connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 2500
                readTimeout = 5000
            }

            val status = connection.responseCode
            val body = if (status in 200..299) {
                connection.inputStream.bufferedReader().use { it.readText() }
            } else {
                val error = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                throw IllegalStateException("PC awareness returned HTTP $status $error")
            }

            parseResult(JSONObject(body))
        }

    suspend fun runWindowsSdrDeepScan(host: String, port: Int): WindowsSdrDeepScanResult =
        withContext(Dispatchers.IO) {
            val cleanHost = host.trim()
            require(cleanHost.isNotBlank()) { "PC sync host is blank" }

            val url = URL("http://$cleanHost:$port/snifferops/sdr/deep-scan")
            val connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 3000
                readTimeout = 8000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }

            connection.outputStream.use { output ->
                output.write(JSONObject().put("requestedAt", System.currentTimeMillis()).toString().toByteArray(Charsets.UTF_8))
            }

            val status = connection.responseCode
            val body = if (status in 200..299) {
                connection.inputStream.bufferedReader().use { it.readText() }
            } else {
                val error = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                throw IllegalStateException("PC SDR scan returned HTTP $status $error")
            }

            parseWindowsSdrDeepScan(JSONObject(body))
        }

    suspend fun pollWindowsSdrDeepScan(host: String, port: Int): WindowsSdrDeepScanResult =
        withContext(Dispatchers.IO) {
            val cleanHost = host.trim()
            require(cleanHost.isNotBlank()) { "PC sync host is blank" }

            val url = URL("http://$cleanHost:$port/snifferops/sdr/deep-scan/status")
            val connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 2500
                readTimeout = 5000
            }

            val status = connection.responseCode
            val body = if (status in 200..299) {
                connection.inputStream.bufferedReader().use { it.readText() }
            } else {
                val error = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                throw IllegalStateException("PC SDR status returned HTTP $status $error")
            }

            parseWindowsSdrDeepScan(JSONObject(body))
        }

    private fun buildSnapshot(devices: List<SignalDevice>, sightings: List<SignalSighting>): JSONObject {
        val sightingsByDevice = sightings.groupBy { it.deviceId }
        return JSONObject().apply {
            put("schema", 1)
            put("nodeId", nodeId())
            put("nodeName", "${Build.MANUFACTURER} ${Build.MODEL}".trim())
            put("capturedAt", System.currentTimeMillis())
            put("location", JSONObject())
            put("completeTypes", JSONArray().apply {
                devices.map { it.signalType.name }.distinct().forEach { put(it) }
            })
            put("signals", JSONArray().apply {
                devices.forEach { device ->
                    put(device.toJson(sightingsByDevice[device.id].orEmpty()))
                }
            })
        }
    }

    private fun SignalDevice.toJson(sightings: List<SignalSighting>): JSONObject = JSONObject().apply {
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
        put("sightings", JSONArray().apply {
            sightings.forEach { sighting ->
                put(JSONObject().apply {
                    put("id", sighting.id)
                    put("capturedAt", sighting.capturedAt)
                    put("signalStrength", sighting.signalStrength)
                    if (sighting.latitude != null && sighting.longitude != null) {
                        put("latitude", sighting.latitude)
                        put("longitude", sighting.longitude)
                        sighting.accuracyMeters?.let { put("accuracyMeters", it.toDouble()) }
                    }
                })
            }
        })
    }

    private fun parseResult(json: JSONObject): AwarenessSyncResult {
        val signals = json.optJSONArray("signals") ?: JSONArray()
        val devices = buildList {
            for (i in 0 until signals.length()) {
                val item = signals.optJSONObject(i) ?: continue
                toSignalDevice(item)?.let { add(it) }
            }
        }
        val profiles = buildList {
            for (i in 0 until signals.length()) {
                val item = signals.optJSONObject(i) ?: continue
                toAwarenessProfile(item)?.let { add(it) }
            }
        }
        return AwarenessSyncResult(
            merged = json.optInt("merged", 0),
            totalSignals = json.optInt("totalSignals", devices.size),
            updatedDevices = devices,
            profiles = profiles,
            acknowledgedSightingIds = json.optJSONArray("acknowledgedSightingIds")?.let { ids ->
                buildList {
                    for (i in 0 until ids.length()) {
                        ids.optString(i).takeIf { it.isNotBlank() }?.let(::add)
                    }
                }
            }.orEmpty()
        )
    }

    private fun parseWindowsSdrDeepScan(json: JSONObject): WindowsSdrDeepScanResult {
        val scan = json.optJSONObject("sdrScan") ?: JSONObject()
        val state = scan.optString("state", "unknown")
        return WindowsSdrDeepScanResult(
            scanId = scan.optString("id", ""),
            state = state,
            message = scan.optString("message", ""),
            running = scan.optBoolean("running", state == "queued" || state == "running"),
            completed = scan.optBoolean("completed", state == "completed"),
            sdrSignals = parseSdrSignals(json.optJSONArray("sdrSignals") ?: JSONArray()),
            awareness = parseResult(json)
        )
    }

    private fun parseSdrSignals(items: JSONArray): List<SdrSignal> = buildList {
        for (i in 0 until items.length()) {
            val item = items.optJSONObject(i) ?: continue
            val frequency = item.optLong("frequencyHz", 0L)
            if (frequency <= 0L) continue
            add(
                SdrSignal(
                    frequency = frequency,
                    bandwidth = parseBandwidth(item.optString("bandwidth")),
                    power = item.optString("powerDb", item.optString("power", "0")).toFloatOrNull()
                        ?: item.optDouble("powerDb", 0.0).toFloat(),
                    modulation = item.optString("modulation", "Unknown"),
                    label = item.optString("label", item.optString("possibleUse", "RF signal")),
                    timestamp = System.currentTimeMillis()
                )
            )
        }
    }

    private fun parseBandwidth(value: String): Long {
        val match = Regex("(\\d+(?:\\.\\d+)?)([kKmMgG]?)").find(value) ?: return 0L
        val number = match.groupValues[1].toDoubleOrNull() ?: return 0L
        val multiplier = when (match.groupValues[2].lowercase()) {
            "k" -> 1_000.0
            "m" -> 1_000_000.0
            "g" -> 1_000_000_000.0
            else -> 1.0
        }
        return (number * multiplier).toLong()
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
            notes = "Synced from PC awareness log; seen ${item.optInt("seenCount", 0)}x from ${item.optInt("nodeCount", 0)} node(s)",
            firstSeen = parseTime(item.optString("firstSeen")),
            lastSeen = parseTime(item.optString("lastSeen")),
            seenCount = item.optInt("seenCount", 1)
        )
    } catch (error: Exception) {
        Log.w(TAG, "Skipping malformed awareness signal", error)
        null
    }

    private fun toAwarenessProfile(item: JSONObject): AwarenessProfile? = try {
        val key = item.optString("key", item.optString("address", item.optString("name", "")))
        val type = runCatching { SignalType.valueOf(item.optString("type", "UNKNOWN")) }.getOrDefault(SignalType.UNKNOWN)
        val threat = runCatching { ThreatLevel.valueOf(item.optString("threatLevel", "UNKNOWN")) }.getOrDefault(ThreatLevel.UNKNOWN)
        AwarenessProfile(
            key = key,
            name = item.optString("name", type.name),
            type = type,
            deviceClass = item.optString("deviceClass", "Synced awareness signal"),
            threatLevel = threat,
            seenCount = item.optInt("seenCount", 1),
            nodeCount = item.optInt("nodeCount", 0),
            lastSeen = parseTime(item.optString("lastSeen")),
            latestEvent = item.optString("latestEvent", ""),
            latitude = item.optDouble("estimatedLatitude", 0.0),
            longitude = item.optDouble("estimatedLongitude", 0.0),
            source = "sync"
        )
    } catch (error: Exception) {
        Log.w(TAG, "Skipping malformed awareness profile", error)
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
