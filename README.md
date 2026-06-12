# SnifferOps

SnifferOps is an Android signal-awareness app tailored for Samsung phones, with an accompanying Samsung watch monitor app and optional RTL-SDR support.

The phone is the primary, standalone recorder. Detection, classification, GPS tagging, and history storage do not depend on Windows, the watch, or an active sync connection.

## Overview

SnifferOps combines a simple tactical dashboard with real Android sensor APIs:

- Wi-Fi scan awareness
- Bluetooth Classic and BLE scanning
- NFC tag detection
- Cellular tower visibility
- Optional direct USB RTL-SDR scanning
- Optional network RTL-SDR mode through `rtl_tcp`
- Samsung watch monitor status display
- Durable on-phone sighting journal with detection-time GPS
- Background Wi-Fi, Bluetooth, BLE, and cellular recording through a foreground service
- Optional replication to the Windows awareness companion

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
| RTL-SDR | Optional RF sweep awareness from direct USB or a network `rtl_tcp` source |

### Samsung Watch Monitor

- Live Wi-Fi / Bluetooth / cellular / SDR counts
- Alert count display
- SDR connection status
- Phone-to-watch sync through the Wear Data Layer

## Local History And GPS

SnifferOps stores two kinds of data in its on-phone Room database:

- Compact device profiles in `signal_devices`
- Append-only detection evidence in `signal_sightings`

Each journal row records the signal ID, detection time, signal strength, and the phone's best available GPS fix at that moment. The foreground scanner service writes these rows while scanning continues in the background, so a drive can be recorded without a Windows connection and synced hours or days later.

Sightings are sampled per device to preserve route movement without recording every repeated callback.

## Windows Replication And Compaction

Windows sync is optional replication, not required operation.

1. `SYNC` sends queued journal rows with their original timestamps and GPS coordinates.
2. Windows assimilates them into its persistent awareness state and returns the exact confirmed sighting IDs.
3. Only after that handshake does `COMPACT PHONE` become available.
4. Compaction deletes only PC-confirmed journal rows. Compact phone profiles and the awareness copy returned by Windows remain available locally.

A failed, partial, or interrupted send deletes nothing. Confirmed rows also survive an app restart until the user explicitly presses `COMPACT PHONE`.

## RTL-SDR

SnifferOps works without an SDR dongle. Wi-Fi, Bluetooth, NFC, and cellular scanning use built-in phone hardware.

### Direct USB Mode

Plug an RTL-SDR Blog V4 or compatible RTL2832U dongle into the phone with USB-C OTG. Android will ask for USB permission, and SnifferOps will use the dongle if available.

### Network SDR Mode

The dongle can stay connected to a Windows/Linux computer running `rtl_tcp`. In the app's SDR screen, enter that computer's LAN IP address and the `rtl_tcp` port, then connect from the phone.

On Windows, download the RTL-SDR Blog command-line tools into the ignored `tools/` folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-rtl-sdr-blog-tools.ps1
```

After binding the dongle to WinUSB, this helper starts the server:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-rtl-tcp.ps1
```

Optional parameters:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-rtl-tcp.ps1 -BindAddress 0.0.0.0 -Port 1234
```

Use `scripts\test-rtl-sdr.ps1` to verify the dongle can be opened by the RTL-SDR Blog tools.

## Building

Requirements:

- Android Studio Ladybug or later
- Android SDK 35
- JDK 17

```bash
git clone https://github.com/jessedaustin93/Sniffer-Ops
cd Sniffer-Ops
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
- `INTERNET` for optional Windows replication and Network SDR mode
- `NFC` for NFC tag detection
- USB Host support for optional direct RTL-SDR mode

## Architecture

```text
app/
  scanner/        WifiScanner, BluetoothScanner, NfcScanner, CellularScanner,
                  RtlSdrScanner, NetworkRtlSdrScanner
  model/          SignalDevice, SignalSighting, SdrSignal, CellTower, NfcTag
  data/           Room profiles, append-only sighting journal, DAO, detection store
  viewmodel/      DashboardViewModel
  ui/             Compose screens and theme
  service/        Foreground Wi-Fi/Bluetooth/BLE/cellular recorder
  util/           DeviceClassifier

wear/
  WearMainActivity    Wear OS Compose UI
  WearDataService     Wearable Data Layer listener
  WearStateHolder     StateFlow for watch state
```

## Legal Notice

This app is for authorized security auditing, network management, and educational use. Always comply with applicable laws and only scan systems and spectrum uses you are allowed to inspect.
