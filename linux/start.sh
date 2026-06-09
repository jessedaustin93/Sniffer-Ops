#!/usr/bin/env bash
# SnifferOps Linux — quick-start launcher.
# Run this directly or let install.sh wire it up to the GNOME app menu.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec python3 snifferops_gui.py "$@"
