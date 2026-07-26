# Ethrox Detect

Ethrox Detect is an Android signal-awareness app tailored for Samsung phones, with an accompanying Samsung watch monitor app and optional replication to a T5810B hub.

The phone is the primary, standalone recorder. Detection, classification, GPS tagging, and history storage do not depend on Windows, the watch, or an active sync connection.

## Overview

Ethrox Detect combines a simple tactical dashboard with real Android sensor APIs:

- Wi-Fi scan awareness
- Bluetooth Classic and BLE scanning
- NFC tag detection
- Cellular tower visibility
- Samsung watch monitor status display
- Durable on-phone sighting journal with detection-time GPS
- Background Wi-Fi, Bluetooth, BLE, and cellular recording through a foreground service
- Optional replication to the T5810B awareness hub over a locally configured private network path

The app is intended for authorized security auditing, network management, and educational use on networks and devices you own or have explicit permission to inspect.

## Features

### Phone App

| Scanner | Detects |
|---|---|
| Wi-Fi | Nearby networks, open/encrypted status, SSID/BSSID, signal strength, basic camera/surveillance keyword classification |
| Bluetooth Classic | Discoverable Bluetooth devices and suspicious name patterns |
| BLE | BLE advertisements, proximity tags, IoT-style devices |
| NFC | Tag ID and supported technologies through Android reader mode |
| Cellular | Visible GSM/WCDMA/LTE/NR cell info exposed by Android |

### Samsung Watch Monitor

- Live Wi-Fi / Bluetooth / cellular counts
- Alert count display
- Phone-to-watch sync through the Wear Data Layer

## Local History And GPS

Ethrox Detect stores two kinds of data in its on-phone Room database:

- Compact device profiles in `signal_devices`
- Append-only detection evidence in `signal_sightings`

Each journal row records the signal ID, detection time, signal strength, and the phone's best available GPS fix at that moment. The foreground scanner service writes these rows while scanning continues in the background, so a drive can be recorded without a Windows connection and synced hours or days later.

Sightings are sampled per device to preserve route movement without recording every repeated callback.

## T5810B Hub Replication And Compaction

Hub sync is optional replication, not required operation. The Android phone is the mobile detector; the T5810B node is the primary awareness, persistence, classification, and correlation hub. Other computers can act as companions, but they are not the hub.

Do not hardcode private Tailscale IPs, MagicDNS names, GPS trails, node IDs, MAC addresses, or captured logs in source or public documentation. Enter the hub address locally on the Hub Sync screen.

1. `SEND TO T5810B HUB` sends queued journal rows with their original timestamps, GPS coordinates, movement-session IDs, and optional motion metadata.
2. The hub assimilates them into persistent awareness state and returns the exact confirmed sighting IDs.
3. Only after that handshake does `COMPACT PHONE` become available.
4. Compaction deletes only hub-confirmed journal rows. Compact phone profiles and the awareness copy returned by the hub remain available locally.

A failed, partial, or interrupted send deletes nothing. Confirmed rows also survive an app restart until the user explicitly presses `COMPACT PHONE`.

Hub transfer and compaction controls live on the dedicated Hub Sync screen. High-rate Bluetooth callbacks are coalesced before batched Room writes while the journal keeps a bounded per-signal sighting cadence.

Android sends schema-1-compatible sync JSON plus optional Linux-hub fields:

- `protocolVersion: 2`
- `nodeRole: mobile_detector`
- capability list for mobile detection, detection-time GPS, movement sessions, BLE advertisement metadata, cellular baseline inputs, and schema-1 backward compatibility
- current node location when permission allows
- per-sighting movement session ID
- per-sighting speed, bearing, and location provider when Android exposes them
- BLE service UUIDs, manufacturer data, service data, Tx power, connectability, and advertised name in the notes field

Scanner type screens show only recently available signals. Older Wi-Fi, Bluetooth, cellular, and NFC observations remain in durable history and on the awareness map instead of filling the live lists.

## Building

Requirements:

- Android Studio Ladybug or later
- Android SDK 35
- JDK 17

```bash
git clone https://github.com/Ethrox-Systems/ethrox-detect
cd ethrox-detect
./gradlew :app:assembleDebug
./gradlew :wear:assembleDebug
```

## Permissions

The phone app requests:

- `ACCESS_FINE_LOCATION` / `ACCESS_COARSE_LOCATION` for Wi-Fi, Bluetooth, and cell scanning visibility
- `BLUETOOTH_SCAN` / `BLUETOOTH_CONNECT` for Bluetooth and BLE scanning
- `READ_PHONE_STATE` for cellular tower info
- `POST_NOTIFICATIONS` for alert notifications
- `FOREGROUND_SERVICE_LOCATION` for persistent background recording
- `INTERNET` for optional T5810B hub replication
- `NFC` for NFC tag detection

## Architecture

```text
app/
  scanner/        WifiScanner, BluetoothScanner, NfcScanner, CellularScanner
  model/          SignalDevice, SignalSighting, CellTower, NfcTag
  data/           Room profiles, append-only sighting journal, DAO, detection store
  viewmodel/      DashboardViewModel
  ui/             Compose screens and theme
  sync/           AwarenessSyncClient and NodeLocationProvider
  service/        Foreground Wi-Fi/Bluetooth/BLE/cellular recorder
  util/           DeviceClassifier

wear/
  WearMainActivity    Wear OS Compose UI
  WearDataService     Wearable Data Layer listener
  WearStateHolder     StateFlow for watch state
```

## Legal Notice

This app is for authorized security auditing, network management, and educational use. Always comply with applicable laws and only scan systems and spectrum uses you are allowed to inspect.
