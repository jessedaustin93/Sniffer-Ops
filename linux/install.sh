#!/usr/bin/env bash
set -e

echo "[snifferops] Installing SnifferOps Linux Companion..."

# RTL-SDR tools
if ! command -v rtl_power &>/dev/null; then
    echo "[snifferops] Installing rtl-sdr..."
    sudo apt-get install -y rtl-sdr librtlsdr-dev
fi

# Python deps
pip3 install --user -r "$(dirname "$0")/requirements.txt"

# Bluetooth tools (usually already present)
sudo apt-get install -y bluetooth bluez

echo "[snifferops] Done. Run with: python3 snifferops_linux.py"
echo ""
echo "Options:"
echo "  --peer 192.168.1.10:8765:windows-pc   sync with Windows node"
echo "  --peer 192.168.1.20:8765:android-hub  sync with another Linux node"
echo "  --sdr-remote 192.168.1.10:1234        use remote rtl_tcp server"
echo "  --no-sdr                              skip RTL-SDR (no hardware needed)"
