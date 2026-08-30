package com.ethrox.detect.util

import com.ethrox.detect.model.ThreatLevel

object DeviceClassifier {

    // Known surveillance / ALPR camera manufacturers
    private val SURVEILLANCE_KEYWORDS = setOf(
        "flock", "verkada", "avigilon", "hikvision", "dahua",
        "axis", "bosch", "pelco", "hanwha", "genetec",
        "milestone", "gallagher", "motorola", "vigilant",
        "jenoptik", "redflex", "conduent", "perceptics"
    )

    private val TRAFFIC_READER_KEYWORDS = setOf(
        "flock", "alpr", "lpr", "license plate", "plate reader",
        "traffic reader", "traffic camera", "speed camera", "red light"
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
        val rules = SignatureEngine.rules
        val ssidLower = ssid.lowercase()
        val mfrLower = manufacturer.lowercase()
        val hasFlockKeyword = hasAny(ssidLower, rules.flockKeywords) || hasAny(mfrLower, rules.flockKeywords)
        val hasHighConfidenceFlock = hasFlockHighConfidence(ssidLower, mfrLower, bssid)
        val needsFlockCorroboration = needsFlockCorroboration(bssid)
        val isFlockLike = hasHighConfidenceFlock || (needsFlockCorroboration && hasFlockKeyword)
        val isTrafficReader = hasAny(ssidLower, TRAFFIC_READER_KEYWORDS) ||
            hasAny(mfrLower, TRAFFIC_READER_KEYWORDS) ||
            hasFlockKeyword
        val isSurveillance = hasAny(ssidLower, SURVEILLANCE_KEYWORDS) ||
            hasAny(mfrLower, SURVEILLANCE_KEYWORDS)
        val isDataStealingTool = hasAny(ssidLower, rules.hostileToolKeywords)

        val deviceClass = when {
            isFlockLike -> "Flock Safety infrastructure"
            needsFlockCorroboration -> "Possible Flock Safety infrastructure"
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
            isFlockLike || needsFlockCorroboration || isTrafficReader || isSurveillance -> ThreatLevel.SUSPICIOUS
            hasAny(ssidLower, NOTICED_KEYWORDS) -> ThreatLevel.UNKNOWN
            !capabilities.contains("WPA") && !capabilities.contains("WEP") -> ThreatLevel.UNKNOWN
            else -> ThreatLevel.SAFE
        }

        return Triple(manufacturer, deviceClass, threat)
    }

    fun classifyBluetooth(
        name: String,
        address: String,
        advertisementMetadata: String = ""
    ): Triple<String, String, ThreatLevel> {
        val manufacturer = lookupOui(address.take(8))
        val rules = SignatureEngine.rules
        val nameLower = name.lowercase()
        val mfrLower = manufacturer.lowercase()
        val metadataLower = advertisementMetadata.lowercase()
        val hasFlockKeyword = hasAny(nameLower, rules.flockKeywords + rules.flockBleNameKeywords) ||
            hasAny(mfrLower, rules.flockKeywords) ||
            hasFlockBleManufacturer(metadataLower)
        val hasHighConfidenceFlock = hasFlockHighConfidence(nameLower, mfrLower, address)
        val needsFlockCorroboration = needsFlockCorroboration(address)
        val isFlockLike = hasHighConfidenceFlock || hasFlockKeyword || (needsFlockCorroboration && hasFlockKeyword)
        val isTrafficReader = hasAny(nameLower, TRAFFIC_READER_KEYWORDS) ||
            hasAny(mfrLower, TRAFFIC_READER_KEYWORDS) ||
            hasFlockKeyword
        val isSurveillance = hasAny(nameLower, SURVEILLANCE_KEYWORDS) ||
            hasAny(mfrLower, SURVEILLANCE_KEYWORDS)
        val isDataStealingTool = hasAny(nameLower, rules.hostileToolKeywords) ||
            hasAny(metadataLower, rules.hostileToolKeywords)
        // Android's manufacturerSpecificData value excludes the company ID.  The
        // scanner records Apple as decimal 76 (0x004c), followed by the payload.
        // 0x12 identifies Find My network advertisements, which are not unique to
        // AirTags, so present this as a tracker *candidate* rather than a certainty.
        val isFindMyCandidate = metadataLower.contains("manufacturerdata=76:12") ||
            metadataLower.contains("manufacturerdata=0x004c:12") ||
            metadataLower.contains("manufacturerdata=004c:12")
        val isTileService = metadataLower.contains("0000feed-0000-1000-8000-00805f9b34fb") ||
            metadataLower.contains("serviceuuid=feed") ||
            metadataLower.contains("serviceuuid=0xfeed")

        val deviceClass = when {
            isFindMyCandidate -> "Find My network accessory / tracker candidate"
            isTileService -> "Tile tracker service"
            isFlockLike -> "Flock Safety infrastructure"
            needsFlockCorroboration -> "Possible Flock Safety infrastructure"
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
            // These signatures identify a tracker-capable ecosystem, not malicious
            // intent.  Keep them visible as suspicious with the raw advertisement
            // evidence retained in notes.
            isFindMyCandidate || isTileService -> ThreatLevel.SUSPICIOUS
            isFlockLike || needsFlockCorroboration || isTrafficReader || isSurveillance -> ThreatLevel.SUSPICIOUS
            hasAny(nameLower, NOTICED_KEYWORDS) -> ThreatLevel.UNKNOWN
            else -> ThreatLevel.SAFE
        }

        val classifiedManufacturer = when {
            isFindMyCandidate -> "Apple / Find My"
            isTileService -> "Tile"
            else -> manufacturer
        }
        return Triple(classifiedManufacturer, deviceClass, threat)
    }

    private fun lookupOui(address: String): String {
        val oui = address.uppercase().take(8).replace("-", ":")
        return KNOWN_OUIS[oui] ?: "Unknown"
    }

    private fun hasFlockHighConfidence(label: String, manufacturer: String, address: String): Boolean {
        val rules = SignatureEngine.rules
        return hasAny(label, rules.flockKeywords) ||
            hasAny(manufacturer, rules.flockKeywords) ||
            rules.flockHighOuis.any { address.uppercase().startsWith(it) }
    }

    private fun needsFlockCorroboration(address: String): Boolean =
        SignatureEngine.rules.flockCorroborationOuis.any { address.uppercase().startsWith(it) }

    private fun hasFlockBleManufacturer(metadata: String): Boolean =
        SignatureEngine.rules.flockBleManufacturerIds.any { id ->
            metadata.contains("manufacturerdata=$id:") || metadata.contains("manufacturerdata=0x$id:")
        }

    private fun hasAny(value: String, keywords: Set<String>): Boolean =
        keywords.any { value.contains(it) }
}
