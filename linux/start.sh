#!/usr/bin/env bash
# Ethrox Detect Linux — quick-start launcher.
# Run this directly or let install.sh wire it up to the GNOME app menu.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec python3 ethrox_detect_gui.py "$@"
