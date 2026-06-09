#!/usr/bin/env bash
# Quick-start script. Edit PEERS below to point at your Windows/Linux nodes.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Add --peer flags for each node you want to sync with, e.g.:
#   PEERS="--peer 192.168.1.10:8765:windows-pc"
PEERS=""

# Uncomment to use a remote rtl_tcp server instead of local hardware:
# SDR_REMOTE="--sdr-remote 192.168.1.10:1234"

exec python3 snifferops_linux.py $PEERS $SDR_REMOTE "$@"
