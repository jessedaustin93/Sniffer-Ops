# SnifferOps Linux Companion

This branch contains the Linux companion version of SnifferOps.

Run this on any Linux machine (Ubuntu 22.04 / 24.04 recommended) that you want to include in your SnifferOps network. It scans local Wi-Fi and Bluetooth, optionally drives an RTL-SDR dongle, consolidates an awareness map, and syncs bi-directionally with the Android app and Windows companion over LAN or Tailscale.

For the Android phone app, see [`codex/android-mobile-app`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/android-mobile-app).  
For the Windows companion, see [`codex/windows-companion`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/windows-companion).

---

## Quick Install

```bash
git clone https://github.com/jessedaustin93/Sniffer-Ops
cd Sniffer-Ops
git checkout codex/linux-companion
cd linux
bash install.sh
```

`install.sh` will:
- Install system dependencies via `apt-get` (GTK4, Bluetooth, RTL-SDR tools, NetworkManager)
- Copy the SVG icon into your user icon theme
- Write a `.desktop` file so SnifferOps appears in the GNOME app menu
- Create a `snifferops` launcher in `~/.local/bin/`

After that, search for **SnifferOps** in the GNOME app grid, or run:

```bash
snifferops
```

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| GTK | 4.0 |
| libadwaita | 1.2+ (1.5 recommended) |
| OS | Ubuntu 22.04 LTS or 24.04 LTS (other systemd/GNOME distros should work) |

All GTK/Adwaita bindings are installed from the system package manager by `install.sh` — no pip installs needed for the GUI itself.

---

## Launch

From the GNOME app menu — search **SnifferOps**.

From the terminal:

```bash
snifferops
# or directly:
python3 /path/to/Sniffer-Ops/linux/snifferops_gui.py
```

---

## Autostart on Login

`install.sh` writes two autostart entries automatically:

- `~/.config/autostart/com.snifferops.linux.desktop` — GNOME session autostart
- `~/.config/systemd/user/snifferops.service` — systemd user service (restarts on crash)

To enable/disable:

```bash
# Disable GNOME autostart
sed -i 's/X-GNOME-Autostart-enabled=true/X-GNOME-Autostart-enabled=false/' \
    ~/.config/autostart/com.snifferops.linux.desktop

# Disable systemd service
systemctl --user disable snifferops.service
```

---

## Tabs

| Tab | What it does |
|---|---|
| **Dashboard** | Animated radar scope, live scanner counts, SDR status badge, START/STOP scan button, 2×3 scanner tile grid (click a tile to jump to that scanner's signal list) |
| **WiFi** | All detected Wi-Fi networks with classification and threat rating |
| **Bluetooth** | BT Classic + BLE devices |
| **SDR Radio** | RTL-SDR frequency sweeps classified against 8 signal lenses |
| **Peers** | Tailscale network discovery, manual peer management, Android/Windows setup info |
| **Settings** | Toggle scanners, set sync port, configure remote rtl_tcp source, clear log |

---

## Sync with Other Nodes

SnifferOps uses a simple HTTP API on port **8765** (configurable) that is wire-compatible across all three platforms.

### Android app

In the Android app's settings, point the sync host at this machine's LAN IP or Tailscale IP:

```
Host: 192.168.x.x    (LAN)
Host: 100.x.x.x      (Tailscale — works across networks)
Port: 8765
```

The Linux app shows both addresses in the **Peers** tab.

### Windows companion

In the Windows companion, add this machine's IP and port as a sync peer. Both nodes will push/pull awareness data automatically every 30 seconds.

### Linux ↔ Linux

Open the **Peers** tab → **Scan for SnifferOps** to auto-discover other nodes on your Tailscale network, or click **Add Peer** and enter the host manually.

Peer configuration is saved to `~/.snifferops/config.json` and reconnects automatically on every launch.

---

## Tailscale (cross-network sync)

Tailscale lets all your nodes sync even when they're on different LANs, VPNs, or mobile data.

```bash
# Install
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

After authenticating, the Linux app detects your Tailscale IP automatically. The **Peers** tab lists all online Tailscale devices and lets you add them with one click.

---

## RTL-SDR Setup

### Local USB dongle

Plug in an RTL2832U-based dongle (RTL-SDR Blog V4 recommended). Enable the scanner in **Settings → RTL-SDR Scanner**. The app calls `rtl_power` under the hood; no extra configuration is needed.

If you get a permission error, add yourself to the `plugdev` group:

```bash
sudo usermod -aG plugdev $USER
# log out and back in
```

### Remote rtl_tcp feed (from Windows or another Linux box)

In **Settings → Remote rtl_tcp**, enter `host:port` (e.g., `192.168.x.x:1234`). The Linux app speaks the same binary RTL-TCP protocol as the Android app.

On the Windows side, use the Windows companion's **START WINDOWS RTL SERVER** button, or run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-rtl-tcp.ps1
```

---

## Signal Lenses

SDR signals are routed through 8 lenses that map frequency ranges to known signal types:

| Lens | Frequency range |
|---|---|
| Broadcast FM | 87.5 – 108 MHz |
| ADS-B (aircraft) | 1090 MHz ± 5 MHz |
| Aviation Voice | 108 – 137 MHz |
| Analog Voice | 136 – 174 MHz, 400 – 512 MHz |
| NOAA Weather | 162.400 – 162.550 MHz |
| P25 Phase 1 | 136 – 512 MHz (P25 sub-bands) |
| POCSAG pager | 152.0 / 157.5 / 462 MHz bands |
| ACARS | 129.125 / 130.025 / 131.550 MHz |

---

## Data

All data is stored locally in `~/.snifferops/`:

| File | Contents |
|---|---|
| `awareness.json` | Detected signals log (merged from all synced nodes) |
| `config.json` | Scanner toggles, port, peer list, SDR remote address |

No data is sent to any external server. All sync is direct node-to-node HTTP on your local network or Tailscale mesh.

---

## File Layout

```
linux/
├── snifferops_gui.py       # GTK4 / Adwaita GUI — main entry point
├── awareness_log.py        # Awareness log + HTTP sync server (port 8765)
├── signal_classifier.py    # Wi-Fi / BT / SDR signal classification
├── install.sh              # Installer (apt deps, icon, .desktop, PATH launcher)
├── start.sh                # Minimal launcher wrapper
├── requirements.txt        # pip extras (GTK bindings come from apt, not pip)
├── assets/
│   ├── snifferops.svg      # App icon (radar scope, dark bg)
│   └── snifferops.desktop  # .desktop template (INSTALL_PATH substituted by install.sh)
├── lenses/
│   └── all_lenses.py       # 8 SDR signal lenses
├── scanners/
│   ├── wifi_scanner.py     # nmcli / iwlist
│   ├── bluetooth_scanner.py# bluetoothctl / hcitool
│   └── rtl_sdr_scanner.py  # rtl_power (local) + rtl_tcp binary protocol (remote)
├── spectrum/
│   └── power_scan.py       # rtl_power CSV parser + peak finder
├── adsb/
│   ├── adsb_decoder.py     # Mode-S / ADS-B frame decoder
│   └── adsb_map.py         # Aircraft map renderer
└── sync/
    └── node_sync.py        # Peer push/pull + background sync loop
```

---

## Notes

- The GUI requires a Wayland or X11 display session. It will not run headless.
- Runtime data, logs, and `__pycache__` directories are gitignored.
- The app is intended for authorized network auditing, security research, and educational use on networks and devices you own or have explicit permission to inspect.
