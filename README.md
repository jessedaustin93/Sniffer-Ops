# Ethrox Detect Linux Companion

This branch contains the Linux companion for Ethrox Detect.

Linux is the local-first awareness hub: it stores observations, serves the LAN
sync API, classifies signals, renders maps, and can initialize Wi-Fi,
Bluetooth, and RTL-SDR scanners when the hardware is available.

For the full Linux operating notes, installation commands, storage paths, and
API details, see [`linux/README.md`](linux/README.md).

## Quick Start

```bash
git clone https://github.com/Ethrox-Systems/ethrox-detect
cd ethrox-detect
./linux/install.sh
ethrox-detect
```

Show the canonical version:

```bash
python3 tools/version.py show
python3 linux/ethrox_detect_linux.py --version
```

## Repository Identity

Active repository:

```text
https://github.com/Ethrox-Systems/ethrox-detect
```

Runtime captures, logs, generated map output, screenshots, and downloaded
RTL-SDR tools are local artifacts and should not be committed.
