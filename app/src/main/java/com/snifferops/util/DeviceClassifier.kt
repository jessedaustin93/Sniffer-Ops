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

    // Known Flipper Zero / hacking tool identifiers
    private val FLIPPER_IDENTIFIERS = setOf(
        "Flipper Zero", "Flipper_", "xRemote", "Evil_Twin",
        "BadUSB", "Marauder", "Deauther"
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

        val deviceClass = when {
            SURVEILLANCE_KEYWORDS.any { ssidLower.contains(it) || mfrLower.contains(it) } -> "Surveillance Camera"
            FLOCK_OUIS.any { bssid.uppercase().startsWith(it) } -> "Flock Safety Camera"
            FLIPPER_IDENTIFIERS.any { ssidLower.contains(it.lowercase()) } -> "Flipper Zero / Hacking Device"
            ssidLower.contains("cam") || ssidLower.contains("ipcam") -> "IP Camera"
            ssidLower.contains("ring") || ssidLower.contains("nest") -> "Smart Doorbell/Camera"
            ssidLower.contains("arlo") || ssidLower.contains("wyze") -> "Smart Camera"
            ssidLower.contains("printer") -> "Printer"
            ssidLower.contains("hp-") || ssidLower.contains("brother") -> "Printer"
            ssidLower.contains("direct") -> "WiFi Direct Device"
            ssidLower.contains("hotspot") || ssidLower.contains("mobile") -> "Mobile Hotspot"
            else -> "WiFi Access Point"
        }

        val threat = when {
            FLOCK_OUIS.any { bssid.uppercase().startsWith(it) } -> ThreatLevel.ALERT
            SURVEILLANCE_KEYWORDS.any { ssidLower.contains(it) || mfrLower.contains(it) } -> ThreatLevel.SUSPICIOUS
            FLIPPER_IDENTIFIERS.any { ssidLower.contains(it.lowercase()) } -> ThreatLevel.ALERT
            ssidLower.contains("evil") || ssidLower.contains("pineapple") -> ThreatLevel.ALERT
            !capabilities.contains("WPA") && !capabilities.contains("WEP") -> ThreatLevel.UNKNOWN
            else -> ThreatLevel.SAFE
        }

        return Triple(manufacturer, deviceClass, threat)
    }

    fun classifyBluetooth(name: String, address: String): Triple<String, String, ThreatLevel> {
        val manufacturer = lookupOui(address.take(8))
        val nameLower = name.lowercase()

        val deviceClass = when {
            FLIPPER_IDENTIFIERS.any { nameLower.contains(it.lowercase()) } -> "Flipper Zero"
            nameLower.contains("flipper") -> "Flipper Zero"
            nameLower.contains("headphone") || nameLower.contains("earbuds") || nameLower.contains("buds") -> "Audio Device"
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
            FLIPPER_IDENTIFIERS.any { nameLower.contains(it.lowercase()) } -> ThreatLevel.ALERT
            nameLower.contains("flipper") -> ThreatLevel.ALERT
            nameLower.contains("pineapple") || nameLower.contains("evil") -> ThreatLevel.ALERT
            else -> ThreatLevel.SAFE
        }

        return Triple(manufacturer, deviceClass, threat)
    }

    fun classifySdrSignal(frequency: Long): Pair<String, String> {
        val mhz = frequency / 1_000_000.0
        val label = when {
            mhz in 87.5..108.0 -> "FM Radio"
            mhz in 108.0..137.0 -> "Aviation VOR/ILS"
            mhz in 137.0..144.0 -> "NOAA Weather Satellite"
            mhz in 144.0..148.0 -> "Amateur (2m)"
            mhz in 148.0..174.0 -> "VHF Government/Military"
            mhz in 154.0..174.0 -> "Public Safety VHF"
            mhz in 162.4..162.55 -> "NOAA Weather Radio"
            mhz in 174.0..216.0 -> "TV Band VHF"
            mhz in 216.0..222.0 -> "Amateur (1.25m)"
            mhz in 400.0..406.0 -> "Meteorological"
            mhz in 406.0..420.0 -> "Government"
            mhz in 420.0..450.0 -> "Amateur (70cm)"
            mhz in 433.0..435.0 -> "ISM 433MHz (IoT/Garage/Car Key)"
            mhz in 450.0..470.0 -> "UHF Land Mobile"
            mhz in 470.0..698.0 -> "TV UHF"
            mhz in 698.0..806.0 -> "LTE Band 17/12"
            mhz in 806.0..869.0 -> "Public Safety 800MHz"
            mhz in 851.0..869.0 -> "P25 / APCO-25 Public Safety"
            mhz in 869.0..894.0 -> "Cellular 850MHz"
            mhz in 902.0..928.0 -> "ISM 915MHz (LoRa/ZigBee)"
            mhz in 928.0..960.0 -> "Cellular GSM 900"
            mhz in 960.0..1215.0 -> "Aviation DME/TACAN"
            mhz in 1090.0..1090.0 -> "ADS-B Aviation"
            mhz in 1215.0..1240.0 -> "GPS L2"
            mhz in 1559.0..1610.0 -> "GPS L1 / GLONASS"
            mhz in 1710.0..1755.0 -> "AWS LTE Band 4"
            mhz in 1850.0..1990.0 -> "PCS 1900 / LTE"
            mhz in 2400.0..2500.0 -> "WiFi 2.4GHz / Bluetooth"
            mhz in 5150.0..5850.0 -> "WiFi 5GHz"
            else -> "Unknown RF Signal"
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
}
