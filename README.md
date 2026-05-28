# SnifferOps

A comprehensive signal detection and analysis app for **Samsung Galaxy S25 Plus** and **Galaxy Watch 8**.

## Overview

SnifferOps is a tactical signal intelligence tool combining the capabilities of:
- **Sophia CivOps** — situational awareness dashboard
- **Bruce** — NFC/RFID scanning and Bluetooth analysis
- **Flipper Zero** — multi-protocol signal detection
- **RTL-SDR** — full spectrum radio frequency analysis (optional USB dongle)

## Features

### Phone App (Galaxy S25 Plus)

| Scanner | Detects |
|---|---|
| **WiFi** | All 2.4/5GHz networks, open/encrypted, Flock cams, IP cameras, rogue APs |
| **Bluetooth Classic** | All paired/discoverable devices, Flipper Zero, trackers |
| **BLE** | All BLE advertisements, proximity tags, IoT sensors |
| **NFC** | MIFARE, NDEF, ISO-DEP (payment cards, ID cards, NFC tags) |
| **Cellular** | GSM/LTE/5G NR towers, MCC/MNC/CID, carrier info |
| **RTL-SDR** | FM, aviation ADS-B, NOAA weather, 433MHz ISM, P25 public safety, and more |

### Watch App (Galaxy Watch 8)
- Live signal counts: WiFi / BT / Cell / SDR
- Alert badge for suspicious/flagged devices
- SDR dongle connection status
- Always-on scanning indicator

### Threat Detection
- **Flock Safety cameras** — detected by SSID keyword + OUI lookup
- **Surveillance cameras** — Hikvision, Dahua, Axis, Verkada, Avigilon, etc.
- **Flipper Zero / hacking tools** — detected by name and identifier
- **Open networks** — flagged for awareness
- **Known tracker beacons** — Tile, AirTag patterns

## RTL-SDR (Optional)

The app works without an SDR dongle. All WiFi, Bluetooth, NFC, and cellular scanning is built-in.

When you plug in an RTL2838/RTL4 dongle via USB-C OTG:
1. The app auto-detects it
2. SDR Scanner activates on the dashboard
3. Frequency sweep covers 11 key bands (FM to ADS-B)

**Supported dongles:**
- RTL2838 / RTL2832U (most common)
- R820T tuner variants
- ezcap EzTV668
- FUNcube Dongle Pro+

## Building

Requirements:
- Android Studio Ladybug or later
- Android SDK 35
- JDK 17

```bash
git clone https://github.com/jessedaustin93/sniffer-ops
cd sniffer-ops
./gradlew :app:assembleDebug
./gradlew :wear:assembleDebug
```

## Permissions

The app requests at runtime:
- `ACCESS_FINE_LOCATION` - required for WiFi and Bluetooth scanning on Android 12+
- `BLUETOOTH_SCAN` / `BLUETOOTH_CONNECT` - BLE and classic Bluetooth
- `READ_PHONE_STATE` - cellular tower info
- `POST_NOTIFICATIONS` - alert notifications
- `NFC` - NFC tag detection (auto, no runtime request)
- USB Host - RTL-SDR dongle (no runtime request needed)

## Architecture

```
app/
  scanner/        WifiScanner, BluetoothScanner, NfcScanner, CellularScanner, RtlSdrScanner
  model/          SignalDevice, SdrSignal, CellTower, NfcTag, ScanSummary
  data/           Room database, DAO
  viewmodel/      DashboardViewModel (central state management)
  ui/
    screen/       Dashboard, WiFi, Bluetooth, NFC, Cellular, SDR, Alerts screens
    theme/        Dark tactical color palette
  service/        Foreground scanner service
  util/           DeviceClassifier (OUI lookup, threat assessment)

wear/             Galaxy Watch 8 companion
  WearMainActivity    Compose UI with ScalingLazyColumn
  WearDataService     Wearable Data Layer listener
  WearStateHolder     StateFlow for watch state
```

## Legal Notice

This app is intended for authorized security auditing, network management, and educational use
on networks and devices you own or have explicit permission to scan. Always comply with applicable laws.
