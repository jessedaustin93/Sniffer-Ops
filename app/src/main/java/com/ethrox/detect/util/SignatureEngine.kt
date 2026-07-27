package com.ethrox.detect.util

import android.content.Context
import android.util.Log
import com.ethrox.detect.model.ThreatLevel
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicReference

data class SignatureRules(
    val flockHighOuis: Set<String>,
    val flockCorroborationOuis: Set<String>,
    val flockKeywords: Set<String>,
    val flockBleManufacturerIds: Set<String>,
    val flockBleNameKeywords: Set<String>,
    val hostileToolKeywords: Set<String>,
    val classifierProfiles: List<ClassifierProfileRule>
) {
    companion object {
        fun fallback(): SignatureRules = SignatureRules(
            flockHighOuis = setOf(
                "70:C9:4E", "3C:91:80", "D8:F3:BC", "80:30:49", "B8:35:32",
                "14:5A:FC", "74:4C:A1", "08:3A:88", "9C:2F:9D", "C0:35:32",
                "94:08:53", "F4:6A:DD", "F8:A2:D6", "24:B2:B9", "00:F4:8D",
                "D0:39:57", "E8:D0:FC", "E0:4F:43", "B8:1E:A4", "70:08:94",
                "58:8E:81", "EC:1B:BD", "58:00:E3", "90:35:EA", "5C:93:A2",
                "64:6E:69", "48:27:EA", "B4:1E:52"
            ),
            flockCorroborationOuis = setOf("E4:AA:EA", "3C:71:BF", "A4:CF:12", "82:6B:F2"),
            flockKeywords = setOf(
                "flock", "flck", "flocksafety", "flock safety", "test_flck",
                "alpr", "lpr", "license plate", "plate reader", "penguin"
            ),
            flockBleManufacturerIds = setOf("0x09c8", "2504"),
            flockBleNameKeywords = setOf("flock", "raven"),
            hostileToolKeywords = setOf(
                "flipper", "flipper zero", "flipper_", "xremote", "evil_twin",
                "evil twin", "badusb", "marauder", "deauth", "deauther",
                "pwnagotchi", "pineapple", "wifi pineapple", "rogue ap",
                "credential", "password", "phish", "skimmer", "bettercap",
                "airgeddon", "wifiphisher", "hostapd-wpe", "eaphammer",
                "mdk4", "mdk3", "karma", "mana", "wifijammer", "wifi jammer"
            ),
            classifierProfiles = fallbackClassifierProfiles()
        )
    }
}

data class ClassifierProfileRule(
    val id: String,
    val family: String,
    val label: String,
    val priority: String,
    val confidence: String,
    val disposition: String,
    val patterns: List<Regex>,
    val requiredPatterns: List<Regex>,
    val excludePatterns: List<Regex>,
    val threatLevel: ThreatLevel,
    val score: Int
) {
    fun matches(text: String): Boolean {
        if (patterns.none { it.containsMatchIn(text) }) return false
        if (requiredPatterns.isNotEmpty() && requiredPatterns.none { it.containsMatchIn(text) }) return false
        return excludePatterns.none { it.containsMatchIn(text) }
    }
}

object SignatureEngine {
    private const val TAG = "SignatureEngine"
    private const val FLOCK_ASSET = "signatures/flock-signatures.json"
    private const val TOOL_ASSET = "signatures/threat-tool-signatures.json"
    private const val CLASSIFIER_RULE_DIR = "signatures/classifier_rules"

    private val rulesRef = AtomicReference(SignatureRules.fallback())

    val rules: SignatureRules
        get() = rulesRef.get()

    fun initialize(context: Context) {
        runCatching {
            val flock = JSONObject(context.assets.open(FLOCK_ASSET).bufferedReader().use { it.readText() })
            val tools = JSONObject(context.assets.open(TOOL_ASSET).bufferedReader().use { it.readText() })
            val classifierProfiles = loadClassifierProfiles(context)
            rulesRef.set(parseRules(flock, tools, classifierProfiles))
            Log.i(TAG, "Loaded Ethrox Detect signature assets (${classifierProfiles.size} classifier profiles)")
        }.onFailure { error ->
            Log.w(TAG, "Using fallback signatures", error)
        }
    }

    private fun parseRules(
        flock: JSONObject,
        tools: JSONObject,
        classifierProfiles: List<ClassifierProfileRule>
    ): SignatureRules {
        val fallback = SignatureRules.fallback()
        val wifi = flock.optJSONObject("wifi") ?: JSONObject()
        val ble = flock.optJSONObject("ble") ?: JSONObject()

        val highOuis = mutableSetOf<String>()
        val corroborationOuis = mutableSetOf<String>()
        wifi.optJSONArray("oui").forEachObject { item ->
            val prefix = item.optString("prefix").normalizedOuiPrefix()
            if (prefix.isBlank()) return@forEachObject
            val requiresCorroboration = item.optBoolean("requires_corroboration", false) ||
                item.optString("confidence", "high").lowercase() != "high" ||
                item.optBoolean("laa", false)
            if (requiresCorroboration) {
                corroborationOuis += prefix
            } else {
                highOuis += prefix
            }
        }

        val bleManufacturerIds = ble.optJSONArray("manufacturer_ids")
            .mapObjects { item -> item.optString("id").normalizedManufacturerId() }
            .filterTo(mutableSetOf()) { it.isNotBlank() }

        return SignatureRules(
            flockHighOuis = highOuis.ifEmpty { fallback.flockHighOuis },
            flockCorroborationOuis = corroborationOuis.ifEmpty { fallback.flockCorroborationOuis },
            flockKeywords = wifi.optJSONArray("ssid_keywords")
                .mapStrings()
                .ifEmpty { fallback.flockKeywords },
            flockBleManufacturerIds = bleManufacturerIds.ifEmpty { fallback.flockBleManufacturerIds },
            flockBleNameKeywords = ble.optJSONArray("name_keywords")
                .mapStrings()
                .ifEmpty { fallback.flockBleNameKeywords },
            hostileToolKeywords = tools.optJSONArray("keywords")
                .mapStrings()
                .ifEmpty { fallback.hostileToolKeywords },
            classifierProfiles = classifierProfiles.ifEmpty { fallback.classifierProfiles }
        )
    }

    private fun loadClassifierProfiles(context: Context): List<ClassifierProfileRule> {
        val profiles = mutableListOf<ClassifierProfileRule>()
        val assets = context.assets.list(CLASSIFIER_RULE_DIR).orEmpty()
            .filter { it.endsWith(".json") }
            .sorted()

        assets.forEach { assetName ->
            val path = "$CLASSIFIER_RULE_DIR/$assetName"
            runCatching {
                val pack = JSONObject(context.assets.open(path).bufferedReader().use { it.readText() })
                pack.optJSONArray("definitions").forEachObject { definition ->
                    parseClassifierProfile(definition)?.let(profiles::add)
                }
            }.onFailure { error ->
                Log.w(TAG, "Skipped classifier pack $path", error)
            }
        }

        return profiles.sortedWith(
            compareByDescending<ClassifierProfileRule> { it.score }
                .thenBy { it.prioritySort }
                .thenBy { it.label }
        )
    }

    private fun parseClassifierProfile(definition: JSONObject): ClassifierProfileRule? {
        val patterns = definition.optJSONArray("patterns").mapRegexes()
        if (patterns.isEmpty()) return null
        val id = definition.optString("id").ifBlank { definition.optString("label") }
        val family = definition.optString("family")
        val priority = definition.optString("priority", "INFO").uppercase()
        val confidence = definition.optString("confidence", "").uppercase()
        val disposition = definition.optString("policy_disposition", "").uppercase()
        return ClassifierProfileRule(
            id = id,
            family = family,
            label = definition.optString("label", id),
            priority = priority,
            confidence = confidence,
            disposition = disposition,
            patterns = patterns,
            requiredPatterns = definition.optJSONArray("required_patterns").mapRegexes(),
            excludePatterns = definition.optJSONArray("exclude_patterns").mapRegexes(),
            threatLevel = threatLevelFor(family, priority, disposition),
            score = definition.optInt("score", scoreFor(priority, disposition))
        )
    }
}

private val ClassifierProfileRule.prioritySort: Int
    get() = when (priority) {
        "HIGH" -> 0
        "CAUTION" -> 1
        "WATCH" -> 2
        "INFO" -> 3
        else -> 4
    }

private fun fallbackClassifierProfiles(): List<ClassifierProfileRule> =
    listOf(
        rawClassifierProfile(
            id = "fallback-flock",
            family = "surveillance.flock",
            label = "Flock Safety infrastructure",
            priority = "HIGH",
            disposition = "HOSTILE",
            patterns = listOf("flock", "flocksafety", "flock safety")
        ),
        rawClassifierProfile(
            id = "fallback-wifi-tool",
            family = "network.offensive_wifi_tool",
            label = "Wi-Fi/BLE assessment tool clue",
            priority = "HIGH",
            disposition = "HOSTILE",
            patterns = listOf("deauth", "marauder", "pwnagotchi", "wifi pineapple", "evil[-_\\s]*twin")
        )
    )

private fun rawClassifierProfile(
    id: String,
    family: String,
    label: String,
    priority: String,
    disposition: String,
    patterns: List<String>
): ClassifierProfileRule {
    val compiled = patterns.mapNotNull { it.toClassifierRegexOrNull() }
    return ClassifierProfileRule(
        id = id,
        family = family,
        label = label,
        priority = priority,
        confidence = "MEDIUM",
        disposition = disposition,
        patterns = compiled,
        requiredPatterns = emptyList(),
        excludePatterns = emptyList(),
        threatLevel = threatLevelFor(family, priority, disposition),
        score = scoreFor(priority, disposition)
    )
}

private fun threatLevelFor(family: String, priority: String, disposition: String): ThreatLevel {
    if (disposition == "HOSTILE") return ThreatLevel.ALERT
    if (family.startsWith("network.") && priority == "HIGH") return ThreatLevel.ALERT
    return when (priority) {
        "HIGH", "CAUTION", "WATCH" -> ThreatLevel.SUSPICIOUS
        else -> ThreatLevel.UNKNOWN
    }
}

private fun scoreFor(priority: String, disposition: String): Int {
    if (disposition == "HOSTILE") return 100
    return when (priority) {
        "HIGH" -> 90
        "CAUTION" -> 70
        "WATCH" -> 55
        "INFO" -> 25
        else -> 10
    }
}

private fun JSONArray?.forEachObject(block: (JSONObject) -> Unit) {
    if (this == null) return
    for (i in 0 until length()) {
        optJSONObject(i)?.let(block)
    }
}

private fun JSONArray?.mapObjects(mapper: (JSONObject) -> String): List<String> {
    if (this == null) return emptyList()
    val values = ArrayList<String>(length())
    for (i in 0 until length()) {
        optJSONObject(i)?.let { values += mapper(it) }
    }
    return values
}

private fun JSONArray?.mapStrings(): Set<String> {
    if (this == null) return emptySet()
    val values = LinkedHashSet<String>(length())
    for (i in 0 until length()) {
        optString(i).trim().lowercase().takeIf { it.isNotBlank() }?.let(values::add)
    }
    return values
}

private fun JSONArray?.mapRegexes(): List<Regex> {
    if (this == null) return emptyList()
    val values = ArrayList<Regex>(length())
    for (i in 0 until length()) {
        optString(i).toClassifierRegexOrNull()?.let(values::add)
    }
    return values
}

private fun String.toClassifierRegexOrNull(): Regex? {
    val pattern = trim()
    if (pattern.isBlank()) return null
    return runCatching { Regex(pattern, RegexOption.IGNORE_CASE) }.getOrNull()
}

private fun String.normalizedOuiPrefix(): String =
    trim()
        .replace("-", ":")
        .uppercase()
        .split(":")
        .take(3)
        .joinToString(":")
        .takeIf { it.length == 8 }
        .orEmpty()

private fun String.normalizedManufacturerId(): String {
    val clean = trim().lowercase()
    val decimal = clean.removePrefix("0x").toIntOrNull(16)?.toString()
    return decimal ?: clean
}
