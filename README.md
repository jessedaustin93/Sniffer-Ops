# Ethrox Detect

Ethrox Detect is a passive signal-awareness toolkit for Wi-Fi, Bluetooth, NFC,
cellular, and SDR workflows. Each platform is standalone first: local
collection and history do not require another node to be online.

Formerly developed under the `SnifferOps` codename.

## Choose A Version

| Platform | Branch | Notes |
|---|---|---|
| **Android** (Samsung) | [`codex/android-mobile-app`](https://github.com/Ethrox-Systems/ethrox-detect/tree/codex/android-mobile-app) | Phone recorder and Samsung Watch companion |
| **Windows** | [`codex/windows-companion`](https://github.com/Ethrox-Systems/ethrox-detect/tree/codex/windows-companion) | Awareness companion, RTL-SDR host, and Windows scanning |
| **Linux** | [`codex/linux-companion`](https://github.com/Ethrox-Systems/ethrox-detect/tree/codex/linux-companion) | GTK4 interface, local scanning, and awareness hub |

## How They Link

The Android phone can record offline for hours or days, then send its stored sightings with their original timestamps and GPS positions. Phone compaction is a separate user action that unlocks only after the receiving companion confirms assimilation.

Windows and Linux can expose awareness endpoints over LAN or Tailscale. Sync behavior is configured per platform; local collection remains available when peers are offline. Windows can also host `rtl_tcp` for Android Network SDR use.

## Quick Start

### Linux

```bash
git clone https://github.com/Ethrox-Systems/ethrox-detect
cd ethrox-detect && git checkout codex/linux-companion
cd linux && bash install.sh
```

### Windows

```powershell
git clone https://github.com/Ethrox-Systems/ethrox-detect
cd ethrox-detect
git checkout codex/windows-companion
windows\Launch-EthroxDetect-Windows.bat
```

### Android

See the [Android branch README](https://github.com/Ethrox-Systems/ethrox-detect/tree/codex/android-mobile-app) for Android Studio build instructions.

---

`main` is intentionally kept as this landing page. Application source lives in the platform branches above.
