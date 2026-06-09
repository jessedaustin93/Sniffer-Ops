# SnifferOps — Linux Companion

A GTK4 / Adwaita desktop app for Linux that scans local wireless signals (Wi-Fi, Bluetooth, RTL-SDR), classifies them, and keeps a shared awareness log in sync with the Android and Windows nodes in your SnifferOps mesh.

Companion branches:
- Android app — [`codex/android-mobile-app`](../../tree/codex/android-mobile-app)
- Windows companion — [`codex/windows-companion`](../../tree/codex/windows-companion)

---

## Requirements

| Dependency | Version | How to get it |
|---|---|---|
| Python | 3.10+ | `python3` from system packages |
| GTK4 + GLib | 4.0 | `apt-get install python3-gi gir1.2-gtk-4.0` |
| libadwaita | 1.2+ (1.5 recommended) | `apt-get install gir1.2-adw-1` |
| BlueZ | 5.50+ | `apt-get install bluez` |
| NetworkManager | any | `apt-get install network-manager` |
| RTL-SDR tools | any | `apt-get install rtl-sdr` (optional) |
| Tailscale | any | `curl -fsSL https://tailscale.com/install.sh \| sh` (optional) |

Tested on Ubuntu 22.04 LTS and 24.04 LTS. Other GNOME / systemd distros should work with minor adjustments.

---

## Install

```bash
git clone https://github.com/jessedaustin93/Sniffer-Ops
cd Sniffer-Ops
git checkout codex/linux-companion
cd linux
bash install.sh
```

`install.sh` does the following in order:

1. Runs `apt-get install` for all system dependencies listed above
2. Copies the three Spy Agency font files from `assets/fonts/` into `~/.local/share/fonts/snifferops/` and runs `fc-cache` so GTK picks them up
3. Installs the app icon (`assets/snifferops.svg`) into `~/.local/share/icons/hicolor/scalable/apps/`
4. Writes a `.desktop` launcher file to `~/.local/share/applications/` so SnifferOps appears in the GNOME app grid
5. Creates a `snifferops` command in `~/.local/bin/` (make sure `~/.local/bin` is on your `$PATH`)
6. Writes a GNOME autostart entry to `~/.config/autostart/com.snifferops.linux.desktop`
7. Writes and enables a systemd user service at `~/.config/systemd/user/snifferops.service`

---

## Launch

From the GNOME app grid — search **SnifferOps**.

From a terminal:

```bash
snifferops
# or directly:
python3 /path/to/Sniffer-Ops/linux/snifferops_gui.py
```

The app registers the D-Bus name `com.snifferops.linux`. If an instance is already running, a second launch exits immediately — the existing window comes to the foreground instead.

---

## The GUI

The interface uses a dark tactical theme (Adwaita dark + custom CSS) with the Spy Agency typeface, a radar scope animation, and a grid of scanner tiles on the main dashboard. The bottom bar has six tabs.

### Dashboard

The main screen shows:

- **Radar scope** — animated sweep that spins while a scan is active; stops when paused
- **Scanner counters** — live counts for Wi-Fi networks, Bluetooth devices, SDR signals, and total merged signals across all nodes
- **SDR badge** — shows `LOCAL`, `REMOTE`, or `OFFLINE` depending on RTL-SDR state
- **START / STOP SCAN** — toggles active scanning across all enabled scanners
- **Scanner tile grid** — six tiles (Wi-Fi, Bluetooth, SDR Radio, NFC, Cellular, Alerts); click the Wi-Fi, Bluetooth, or SDR tiles to jump to that scanner's signal list page

### WiFi

Detected Wi-Fi access points with SSID, BSSID, signal strength (dBm), channel, frequency band, and security type. Each row is classified (e.g. open network, hidden SSID, known vendor) and assigned a threat level.

**How it scans:** calls `nmcli --get-values SSID,BSSID,SIGNAL,CHAN,FREQ,SECURITY dev wifi list` as the primary method. Falls back to `iwlist scanning` if NetworkManager is not available.

### Bluetooth

Bluetooth Classic and BLE devices with MAC address, device name (if advertised), RSSI, device class, and manufacturer.

**How it scans:** calls `bluetoothctl --timeout 8 scan on` then `bluetoothctl devices` followed by per-device `bluetoothctl info <MAC>` to pull class and manufacturer data. Falls back to `hcitool scan --flush` on systems with older BlueZ.

### SDR Radio

Spectrum sweep results classified against eight signal lenses. Each row shows center frequency, signal strength, bandwidth estimate, and the matched lens (e.g. "Broadcast FM", "ADS-B Aircraft Map").

**How it scans:** runs `rtl_power -f <start>:<stop>:<step> -g 0 -i 1` and parses the CSV output. Peak detection runs over the power array to identify active signals. Matched peaks are passed to the lens pipeline to assign a signal type.

Remote IQ input via `rtl_tcp` is also supported — see [RTL-SDR Remote Feed](#rtl-sdr-remote-feed) below.

### Peers

Shows your local Tailscale IP under **This Node**. Lists all online Tailscale devices detected by `tailscale status --json` under **Tailscale Network** with a one-click **Add** button. A separate **Manual Peers** section lists every configured sync peer with:

- Last sync timestamp (updated after each successful sync cycle)
- Online/offline indicator dot (green = health check passed, red = unreachable)
- **Sync now** button to force an immediate push/pull cycle with that peer
- **Remove** button

### Settings

- Enable/disable individual scanners (Wi-Fi, Bluetooth, RTL-SDR)
- Sync port (default 8765)
- Remote `rtl_tcp` source address (host:port)
- **Clear Awareness Log** — wipes `awareness.json` after confirmation

---

## Scanning in More Detail

### RTL-SDR Local Dongle

Plug in an RTL2832U-based dongle. Enable the scanner in **Settings → RTL-SDR Scanner**. The app calls `rtl_power` directly — no SDR# or separate SDR application needed.

If the device shows a permissions error:

```bash
sudo usermod -aG plugdev $USER
# log out and back in
```

Modern kernels ship a generic DVB-T driver that conflicts with `librtlsdr`. If `rtl_power` reports the device is in use:

```bash
sudo modprobe -r dvb_usb_rtl28xxu
```

### RTL-SDR Remote Feed

If your RTL-SDR dongle is connected to a different machine (e.g. the Windows companion), you can receive its IQ stream over the network. In **Settings → Remote rtl_tcp**, enter the host and port of the `rtl_tcp` server:

```
192.168.x.x:1234
```

The Linux app speaks the standard `rtl_tcp` binary protocol, the same one used by the Android app. On the Windows side, the companion's **START WINDOWS RTL SERVER** button starts the server.

---

## Signal Lenses

When a spectrum peak is detected, the app routes it through eight lenses in priority order. The first lens whose frequency range matches wins.

| Lens | Frequency range | Signal type |
|---|---|---|
| ADS-B Aircraft | 1089.5 – 1090.5 MHz | Mode-S transponder frames |
| Broadcast FM | 87.5 – 108 MHz | Wideband FM radio |
| Aviation Airband | 118 – 137 MHz | AM voice (aircraft / ATC) |
| NOAA Weather Radio | 162.40 – 162.55 MHz | NFM weather broadcasts |
| Analog Voice / Amateur | 144–148, 148–174, 420–450, 450–470 MHz | NFM land mobile / ham |
| P25 Phase 1 | 136 – 512 MHz P25 sub-bands | Digital trunked voice |
| POCSAG Pager | 152.0, 157.5, 462 MHz bands | One-way pager protocol |
| ACARS | 129.125, 130.025, 131.550 MHz | Aircraft data link |

---

## Awareness Network

All three platforms (Linux, Windows, Android) share a common JSON awareness log and a wire-compatible HTTP sync protocol on port **8765**.

### HTTP API

The Linux app starts a local HTTP server on `0.0.0.0:8765` when it launches.

| Endpoint | Method | Description |
|---|---|---|
| `/snifferops/health` | GET | Returns `{"ok": true, "nodeId": "..."}` — used for peer probing |
| `/snifferops/awareness` | GET | Returns the full merged signal log as a JSON snapshot |
| `/snifferops/sync` | POST | Accepts a snapshot from a peer; merges it into the local log; returns the local snapshot so the caller can merge in the other direction |

### Sync cycle

The sync manager (`sync/node_sync.py`) runs a background thread that wakes every 5 seconds and checks each peer:

1. If the peer is due for a sync (based on its backoff timer), it POSTs the local awareness snapshot to `/snifferops/sync`
2. The peer merges the incoming data and returns its own full snapshot in the response body
3. The local node merges that response — both sides are now up to date in a single round trip
4. If the POST fails, the app falls back to a GET on `/snifferops/awareness` to at least pull what the peer has

Failed syncs use exponential backoff: first failure → wait 30s, second → 60s, third → 120s, up to a maximum of 5 minutes. A successful sync resets the backoff to the base interval.

### Tailscale auto-discovery

At startup and every 60 seconds, the app runs `tailscale status --json` to get the list of online Tailscale peers. For each peer, it probes `:8765/snifferops/health`. Any peer that responds is automatically added to the sync list (tagged `via: tailscale`) and saved to `config.json`. No manual entry is needed — as long as both machines are on the same Tailscale network and SnifferOps is running, they will find each other within a minute of launch.

---

## Tailscale Setup

Tailscale lets all three nodes sync across different LANs, VPNs, or cellular connections — no port forwarding needed.

```bash
# Install
curl -fsSL https://tailscale.com/install.sh | sh

# Authenticate (opens a browser login)
sudo tailscale up

# Verify your Tailscale IP (shown in Peers tab as well)
tailscale ip -4
```

Once all three devices are authenticated to the same Tailscale account, the **Peers** tab will list them and let you add them with one click. The sync manager will also pick them up automatically at the next discovery pass.

---

## Autostart

`install.sh` sets up two autostart mechanisms:

**GNOME session autostart** (`~/.config/autostart/com.snifferops.linux.desktop`)  
Launches SnifferOps when your desktop session starts. Controlled from GNOME Tweaks → Startup Applications, or:

```bash
# Disable
sed -i 's/X-GNOME-Autostart-enabled=true/X-GNOME-Autostart-enabled=false/' \
    ~/.config/autostart/com.snifferops.linux.desktop
```

**systemd user service** (`~/.config/systemd/user/snifferops.service`)  
Runs after `tailscaled.service` comes up. Restarts automatically if the process crashes (`Restart=on-failure`, 10 second delay). Controlled with:

```bash
systemctl --user status snifferops
systemctl --user stop snifferops
systemctl --user disable snifferops
```

Both mechanisms use the D-Bus single-instance check, so if one starts SnifferOps and then the other fires, the second launch exits cleanly.

---

## Data and Privacy

All data stays on your machines. Nothing is sent to any external service.

| Path | Contents |
|---|---|
| `~/.snifferops/awareness.json` | Merged signal log — all signals seen by any synced node |
| `~/.snifferops/config.json` | Scanner toggles, sync port, peer list, remote SDR address |

Sync traffic is direct HTTP between nodes on your LAN or Tailscale mesh. If you use Tailscale, all traffic is end-to-end encrypted by WireGuard. The awareness log stores signal metadata (SSID, MAC, frequency, signal strength, classification) but not payload data — the app does not capture packet contents.

---

## File Layout

```
linux/
├── snifferops_gui.py        # GTK4 / Adwaita GUI — main entry point
├── awareness_log.py         # Awareness log + HTTP sync server (port 8765)
├── signal_classifier.py     # Wi-Fi / Bluetooth / SDR threat classification
├── install.sh               # Installer: apt deps, fonts, icon, .desktop, autostart
├── start.sh                 # Thin launcher wrapper
├── requirements.txt         # pip extras (GTK bindings come from apt, not pip)
├── assets/
│   ├── fonts/               # Spy Agency TTF files (loaded at runtime via fontconfig)
│   ├── snifferops.svg       # App icon
│   └── snifferops.desktop   # .desktop template (INSTALL_PATH filled by install.sh)
├── scanners/
│   ├── wifi_scanner.py      # nmcli primary, iwlist fallback
│   ├── bluetooth_scanner.py # bluetoothctl primary, hcitool fallback
│   └── rtl_sdr_scanner.py   # rtl_power (local USB) + rtl_tcp binary protocol (remote)
├── lenses/
│   ├── lens_contract.py     # Lens base class and LensDirective
│   └── all_lenses.py        # Eight signal lenses (FM, ADS-B, aviation, weather, etc.)
├── spectrum/
│   └── power_scan.py        # rtl_power CSV parser and peak finder
├── adsb/
│   ├── adsb_decoder.py      # Mode-S / ADS-B frame decoder
│   └── adsb_map.py          # Aircraft position map renderer
└── sync/
    └── node_sync.py         # Background sync manager: discovery, push/pull, backoff
```

---

## Notes

- Requires a live Wayland or X11 display session. Does not run headless.
- The GUI font (Spy Agency) is loaded at runtime from `assets/fonts/` via fontconfig — no system font install required.
- `__pycache__`, runtime data, and log files are gitignored and will not be committed.
- This tool is intended for authorized network auditing, security research, and educational use on networks and devices you own or have explicit permission to inspect.
