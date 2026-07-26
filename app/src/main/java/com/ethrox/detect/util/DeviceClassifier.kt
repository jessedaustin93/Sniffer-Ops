package com.ethrox.detect.util

import com.ethrox.detect.model.ThreatLevel

object DeviceClassifier {

    // Mirrored from Ethrox Detect shared signatures/flock-signatures.json.
    private val FLOCK_OUIS = setOf(
        "70:C9:4E", "3C:91:80", "D8:F3:BC", "80:30:49", "B8:35:32",
        "14:5A:FC", "74:4C:A1", "08:3A:88", "9C:2F:9D", "C0:35:32",
        "94:08:53", "F4:6A:DD", "F8:A2:D6", "24:B2:B9", "00:F4:8D",
        "D0:39:57", "E8:D0:FC", "E0:4F:43", "B8:1E:A4", "70:08:94",
        "58:8E:81", "EC:1B:BD", "58:00:E3", "90:35:EA", "5C:93:A2",
        "64:6E:69", "48:27:EA", "B4:1E:52"
    )

    private val FLOCK_REQUIRES_CORROBORATION_OUIS = setOf(
        "E4:AA:EA", "3C:71:BF", "A4:CF:12", "82:6B:F2"
    )

    // Known surveillance / ALPR camera manufacturers
    private val SURVEILLANCE_KEYWORDS = setOf(
        "flock", "verkada", "avigilon", "hikvision", "dahua",
        "axis", "bosch", "pelco", "hanwha", "genetec",
        "milestone", "gallagher", "motorola", "vigilant",
        "jenoptik", "redflex", "conduent", "perceptics"
    )

    private val TRAFFIC_READER_KEYWORDS = setOf(
        "flock", "alpr", "lpr", "license plate", "plate reader",
        "traffic reader", "traffic camera", "speed camera", "red light",
        "flck", "flocksafety", "flock safety", "test_flck"
    )

    // Tooling that can be used for interception, impersonation, or data capture.
    private val DATA_STEALING_KEYWORDS = setOf(
        "flipper", "flipper zero", "flipper_", "xremote", "evil_twin",
        "evil twin", "badusb", "marauder", "deauther", "pwnagotchi",
        "pineapple", "wifi pineapple", "rogue ap", "credential",
        "password", "phish", "skimmer", "bettercap", "airgeddon",
        "wifiphisher", "hostapd-wpe", "eaphammer", "mdk4", "mdk3",
        "karma", "mana", "wifijammer", "wifi jammer"
    )

    private val NOTICED_KEYWORDS = setOf(
        "direct", "wifi direct", "beacon", "tracker", "airtag", "tile",
        "unknown ble", "ble tag", "sensor"
    )

    // OUI database (first 3 octets of MAC -> manufacturer)
    private val KNOWN_OUIS = mapOf(
        "B4:1E:52" to "Flock Safety",
        "00:11:22" to "Citroen",
        "DC:A6:32" to "Raspberry Pi Foundation",
        "B8:27:EB" to "Raspberry Pi Foundation",
        "E4:5F:01" to "Raspberry Pi Foundation",
        "3C:22:FB" to "Apple",
        "A4:C3:F0" to "Apple",
        "00:17:F2" to "Apple",
        "00:1F:5B" to "Apple",
        "08:00:27" to "VirtualBox",
        "00:50:56" to "VMware",
        "FC:01:7C" to "Google",
        "F4:F5:D8" to "Google",
        "00:1A:11" to "Google",
        "54:60:09" to "Google",
        "AC:37:43" to "HTC",
        "00:26:BB" to "Apple",
        "44:00:10" to "Apple",
        "00:0A:E4" to "Wistron",
        "00:1B:77" to "Intel",
        "00:23:14" to "Intel",
        "00:27:10" to "Intel"
    )

    fun classifyWifi(ssid: String, bssid: String, capabilities: String): Triple<String, String, ThreatLevel> {
        val manufacturer = lookupOui(bssid)
        val ssidLower = ssid.lowercase()
        val mfrLower = manufacturer.lowercase()
        val isFlockLike = isFlockLike(ssidLower, mfrLower, bssid)
        val isTrafficReader = hasAny(ssidLower, TRAFFIC_READER_KEYWORDS) ||
            hasAny(mfrLower, TRAFFIC_READER_KEYWORDS)
        val isSurveillance = hasAny(ssidLower, SURVEILLANCE_KEYWORDS) ||
            hasAny(mfrLower, SURVEILLANCE_KEYWORDS)
        val isDataStealingTool = hasAny(ssidLower, DATA_STEALING_KEYWORDS)

        val deviceClass = when {
            isFlockLike -> "Flock Safety infrastructure"
            needsFlockCorroboration(bssid) -> "Possible Flock Safety infrastructure"
            isTrafficReader -> "Traffic reader / ALPR device"
            isSurveillance -> "Camera / surveillance WiFi"
            isDataStealingTool -> "Hostile WiFi / assessment tool"
            ssidLower.contains("cam") || ssidLower.contains("ipcam") -> "Camera WiFi"
            ssidLower.contains("ring") || ssidLower.contains("nest") -> "Doorbell / camera WiFi"
            ssidLower.contains("arlo") || ssidLower.contains("wyze") -> "Camera WiFi"
            ssidLower.contains("printer") -> "Printer"
            ssidLower.contains("hp-") || ssidLower.contains("brother") -> "Printer"
            ssidLower.contains("direct") -> "WiFi Direct device"
            ssidLower.contains("hotspot") || ssidLower.contains("mobile") -> "Phone / hotspot WiFi"
            ssidLower.contains("roku") || ssidLower.contains("tv") || ssidLower.contains("chromecast") ||
                ssidLower.contains("firetv") || ssidLower.contains("fire tv") -> "TV / media WiFi"
            ssidLower.contains("router") || ssidLower.contains("gateway") || ssidLower.contains("mesh") ||
                ssidLower.contains("eero") || ssidLower.contains("orbi") || ssidLower.contains("netgear") ||
                ssidLower.contains("tplink") || ssidLower.contains("tp-link") || ssidLower.contains("linksys") ->
                "WiFi access point"
            else -> "WiFi wireless device"
        }

        val threat = when {
            isDataStealingTool -> ThreatLevel.ALERT
            isFlockLike || needsFlockCorroboration(bssid) || isTrafficReader || isSurveillance -> ThreatLevel.SUSPICIOUS
            hasAny(ssidLower, NOTICED_KEYWORDS) -> ThreatLevel.UNKNOWN
            !capabilities.contains("WPA") && !capabilities.contains("WEP") -> ThreatLevel.UNKNOWN
            else -> ThreatLevel.SAFE
        }

        return Triple(manufacturer, deviceClass, threat)
    }

    fun classifyBluetooth(name: String, address: String): Triple<String, String, ThreatLevel> {
        val manufacturer = lookupOui(address.take(8))
        val nameLower = name.lowercase()
        val mfrLower = manufacturer.lowercase()
        val isFlockLike = isFlockLike(nameLower, mfrLower, address)
        val isTrafficReader = hasAny(nameLower, TRAFFIC_READER_KEYWORDS) ||
            hasAny(mfrLower, TRAFFIC_READER_KEYWORDS)
        val isSurveillance = hasAny(nameLower, SURVEILLANCE_KEYWORDS) ||
            hasAny(mfrLower, SURVEILLANCE_KEYWORDS)
        val isDataStealingTool = hasAny(nameLower, DATA_STEALING_KEYWORDS)

        val deviceClass = when {
            isFlockLike -> "Flock Safety infrastructure"
            needsFlockCorroboration(address) -> "Possible Flock Safety infrastructure"
            isTrafficReader -> "Traffic reader / ALPR device"
            isSurveillance -> "Camera / surveillance device"
            isDataStealingTool -> "Hostile Bluetooth / assessment tool"
            nameLower.contains("headphone") || nameLower.contains("earbuds") || nameLower.contains("buds") -> "Audio device"
            nameLower.contains("watch") || nameLower.contains("band") -> "Wearable"
            nameLower.contains("keyboard") -> "Keyboard"
            nameLower.contains("mouse") -> "Mouse"
            nameLower.contains("speaker") -> "Speaker"
            nameLower.contains("phone") || nameLower.contains("pixel") || nameLower.contains("iphone") -> "Smartphone"
            nameLower.contains("laptop") || nameLower.contains("macbook") -> "Laptop"
            nameLower.contains("car") || nameLower.contains("vehicle") -> "Vehicle"
            nameLower.contains("tile") || nameLower.contains("airtag") -> "Tracker"
            else -> "Bluetooth Device"
        }

        val threat = when {
            isDataStealingTool -> ThreatLevel.ALERT
            isFlockLike || needsFlockCorroboration(address) || isTrafficReader || isSurveillance -> ThreatLevel.SUSPICIOUS
            hasAny(nameLower, NOTICED_KEYWORDS) -> ThreatLevel.UNKNOWN
            else -> ThreatLevel.SAFE
        }

        return Triple(manufacturer, deviceClass, threat)
    }

    private fun lookupOui(address: String): String {
        val oui = address.uppercase().take(8).replace("-", ":")
        return KNOWN_OUIS[oui] ?: "Unknown"
    }

    private fun isFlockLike(label: String, manufacturer: String, address: String): Boolean =
        label.contains("flock") ||
            label.contains("flck") ||
        manufacturer.contains("flock") ||
            FLOCK_OUIS.any { address.uppercase().startsWith(it) }

    private fun needsFlockCorroboration(address: String): Boolean =
        FLOCK_REQUIRES_CORROBORATION_OUIS.any { address.uppercase().startsWith(it) }

    private fun hasAny(value: String, keywords: Set<String>): Boolean =
        keywords.any { value.contains(it) }
}
