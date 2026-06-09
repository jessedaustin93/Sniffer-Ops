# SnifferOps

SnifferOps is a passive signal scanner for Wi-Fi, Bluetooth, NFC, cellular, and SDR workflows. All three versions share a common awareness map that syncs bi-directionally over LAN or Tailscale — detections on any node appear on all of them in real time.

## Choose a Version

| Platform | Branch | Notes |
|---|---|---|
| **Android** (Samsung) | [`codex/android-mobile-app`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/android-mobile-app) | Phone + Samsung Watch companion |
| **Windows** | [`codex/windows-companion`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/windows-companion) | RTL-SDR server host, Windows-side scanning |
| **Linux** | [`codex/linux-companion`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/linux-companion) | GTK4 GUI, Tailscale sync, awareness hub |

## How They Link

Each node runs its own awareness log and exposes an HTTP sync endpoint on port **8765**. Nodes push and pull signal data from each other automatically every 30 seconds. You can add any mix of Android, Windows, and Linux nodes to a shared mesh.

```
Android app  ──►  Linux node  ◄──►  Windows companion
                      │
                 Tailscale / LAN
                      │
              (other Linux nodes)
```

**Typical setup:**
- Windows machine hosts the RTL-SDR dongle and runs `rtl_tcp` on port 1234
- Android app connects to it over the LAN for Network SDR data
- Linux companion scans local Wi-Fi + Bluetooth and syncs the awareness map with both
- All three nodes share the same signal picture in real time

## Quick Start

### Linux

```bash
git clone https://github.com/jessedaustin93/Sniffer-Ops
cd Sniffer-Ops && git checkout codex/linux-companion
cd linux && bash install.sh
```

Then search **SnifferOps** in the GNOME app grid, or run `snifferops` in a terminal.

### Windows

```powershell
git clone https://github.com/jessedaustin93/Sniffer-Ops
cd Sniffer-Ops
git checkout codex/windows-companion
windows\Launch-SnifferOps-Windows.bat
```

### Android

See the [Android branch README](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/android-mobile-app) for build instructions (requires Android Studio).

---

`main` is intentionally kept as this landing page. All app source lives in the version branches above.
