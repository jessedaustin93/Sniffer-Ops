package com.snifferops.util

import com.snifferops.model.ThreatLevel

object DeviceClassifier {

    // Known Flock Safety camera MAC prefixes (OUI)
    private val FLOCK_OUIS = setOf(
        "00:1A:2B", "DC:A6:32", "B8:27:EB", "E4:5F:01",
        "00:E0:4C", "2C:F0:5D", "A4:CF:12", "3C:71:BF"
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
        "traffic reader", "traffic camera", "speed camera", "red light"
    )

    // Tooling that can be used for interception, impersonation, or data capture.
    private val DATA_STEALING_KEYWORDS = setOf(
        "flipper", "flipper zero", "flipper_", "xremote", "evil_twin",
        "evil twin", "badusb", "marauder", "deauther", "pwnagotchi",
        "pineapple", "wifi pineapple", "rogue ap", "credential",
        "password", "phish", "skimmer", "sniffer"
    )

    private val NOTICED_KEYWORDS = setOf(
        "direct", "wifi direct", "beacon", "tracker", "airtag", "tile",
        "unknown ble", "ble tag", "sensor"
    )

    // OUI database (first 3 octets of MAC -> manufacturer)
    private val KNOWN_OUIS = mapOf(
        "00:0C:E7" to "Flock Safety",
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
            isFlockLike -> "Possible Flock camera"
            isTrafficReader -> "Traffic reader / ALPR device"
            isSurveillance -> "Camera / surveillance WiFi"
            isDataStealingTool -> "Data-capture / hacking device"
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
            isFlockLike || isTrafficReader || isSurveillance -> ThreatLevel.SUSPICIOUS
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
            isFlockLike -> "Possible Flock camera"
            isTrafficReader -> "Traffic reader / ALPR device"
            isSurveillance -> "Camera / surveillance device"
            isDataStealingTool -> "Data-capture / hacking device"
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
            isFlockLike || isTrafficReader || isSurveillance -> ThreatLevel.SUSPICIOUS
            hasAny(nameLower, NOTICED_KEYWORDS) -> ThreatLevel.UNKNOWN
            else -> ThreatLevel.SAFE
        }

        return Triple(manufacturer, deviceClass, threat)
    }

    fun classifySdrSignal(frequency: Long): Pair<String, String> {
        val mhz = frequency / 1_000_000.0
        val label = when {
            mhz in 87.5..108.0 -> "Broadcast FM radio"
            mhz in 108.0..118.0 -> "Aviation nav beacon"
            mhz in 118.0..137.0 -> "Aviation airband"
            mhz in 137.0..138.0 -> "NOAA satellite"
            mhz in 144.0..148.0 -> "Amateur 2m"
            mhz in 162.4..162.55 -> "NOAA Weather Radio"
            mhz in 150.0..174.0 -> "VHF land mobile"
            mhz in 174.0..216.0 -> "VHF TV / broadcast"
            mhz in 216.0..222.0 -> "Amateur (1.25m)"
            mhz in 400.0..406.0 -> "Meteorological"
            mhz in 406.0..420.0 -> "Government"
            mhz in 433.0..435.0 -> "433 MHz ISM device"
            mhz in 420.0..450.0 -> "Amateur 70cm"
            mhz in 450.0..470.0 -> "UHF land mobile"
            mhz in 470.0..698.0 -> "UHF TV / broadcast"
            mhz in 698.0..806.0 -> "LTE / cellular 700"
            mhz in 851.0..869.0 -> "P25 / trunked radio"
            mhz in 806.0..869.0 -> "800 MHz public safety"
            mhz in 869.0..894.0 -> "Cellular 850"
            mhz in 902.0..928.0 -> "915 MHz ISM device"
            mhz in 928.0..960.0 -> "Cellular GSM 900"
            mhz in 978.0..979.0 -> "ADS-B UAT aircraft"
            mhz in 1090.0..1091.0 -> "ADS-B aircraft"
            mhz in 960.0..1215.0 -> "Aviation DME/TACAN"
            mhz in 1215.0..1240.0 -> "GPS L2"
            mhz in 1559.0..1610.0 -> "GPS L1 / GLONASS"
            mhz in 1710.0..1990.0 -> "Cellular AWS/PCS"
            mhz in 2400.0..2500.0 -> "2.4 GHz WiFi / Bluetooth"
            mhz in 5150.0..5850.0 -> "5 GHz WiFi"
            else -> "RF signal"
        }

        val modulation = when {
            mhz in 87.5..108.0 -> "FM/RBDS"
            mhz in 108.0..137.0 -> "AM/VOR"
            mhz in 433.0..435.0 -> "OOK/FSK"
            mhz in 851.0..869.0 -> "P25/TDMA"
            mhz in 1090.0..1091.0 -> "PPM/ADS-B"
            else -> "Unknown"
        }

        return Pair(label, modulation)
    }

    private fun lookupOui(address: String): String {
        val oui = address.uppercase().take(8).replace("-", ":")
        return KNOWN_OUIS[oui] ?: "Unknown"
    }

    private fun isFlockLike(label: String, manufacturer: String, address: String): Boolean =
        label.contains("flock") ||
            manufacturer.contains("flock") ||
            FLOCK_OUIS.any { address.uppercase().startsWith(it) }

    private fun hasAny(value: String, keywords: Set<String>): Boolean =
        keywords.any { value.contains(it) }
}
