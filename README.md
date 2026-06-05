# SnifferOps

SnifferOps is an Android signal-awareness app tailored for Samsung phones, with an accompanying Samsung watch monitor app and optional RTL-SDR support.

## Overview

SnifferOps combines a simple tactical dashboard with real Android sensor APIs:

- Wi-Fi scan awareness
- Bluetooth Classic and BLE scanning
- NFC tag detection
- Cellular tower visibility
- Optional direct USB RTL-SDR scanning
- Optional network RTL-SDR mode through `rtl_tcp`
- Samsung watch monitor status display

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
- `INTERNET` for optional Network SDR mode
- `NFC` for NFC tag detection
- USB Host support for optional direct RTL-SDR mode

## Architecture

```text
app/
  scanner/        WifiScanner, BluetoothScanner, NfcScanner, CellularScanner,
                  RtlSdrScanner, NetworkRtlSdrScanner
  model/          SignalDevice, SdrSignal, CellTower, NfcTag, ScanSummary
  data/           Room database and DAO
  viewmodel/      DashboardViewModel
  ui/             Compose screens and theme
  service/        Foreground scanner service
  util/           DeviceClassifier

wear/
  WearMainActivity    Wear OS Compose UI
  WearDataService     Wearable Data Layer listener
  WearStateHolder     StateFlow for watch state
```

## Legal Notice

This app is for authorized security auditing, network management, and educational use. Always comply with applicable laws and only scan systems and spectrum uses you are allowed to inspect.
