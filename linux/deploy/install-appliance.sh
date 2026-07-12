#!/usr/bin/env bash
# Ethrox Detect — headless appliance installer.
#
# Turns a clean Debian/Raspberry Pi OS Lite (Bookworm) system into a
# "Ethrox Detect only" node: no GTK, installed under /opt/ethrox-detect, run by a
# dedicated `ethrox-detect` system user via a system systemd service.
#
# Idempotent: running twice on a clean system leaves an identical, healthy
# result with the service enabled.
#
# Usage:  sudo ./install-appliance.sh [--no-enable]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"   # the linux/ tree
# shellcheck source=lib-install.sh
. "$SCRIPT_DIR/lib-install.sh"

ENABLE_SERVICE=1
[ "${1:-}" = "--no-enable" ] && ENABLE_SERVICE=0

require_root

# ── 1. System packages (headless: no GTK/WebKit/adwaita) ─────────────────────
log "installing system packages"
apt-get update -qq
apt_install \
    python3 python3-venv python3-pip \
    bluetooth bluez \
    rtl-sdr librtlsdr-dev \
    network-manager wireless-tools

# ── 2. Service user + directories ────────────────────────────────────────────
ensure_system_user "$ETHROX_DETECT_USER" "$ETHROX_DETECT_DATA_DIR"
# Hardware access for BlueZ / NetworkManager / RTL-SDR under the service user.
add_user_groups "$ETHROX_DETECT_USER" bluetooth netdev plugdev dialout
install_rtlsdr_udev

ensure_dir "$ETHROX_DETECT_PREFIX" "$ETHROX_DETECT_USER" 0755
ensure_dir "$ETHROX_DETECT_DATA_DIR" "$ETHROX_DETECT_USER" 0750

# ── 3. Copy the app into /opt/ethrox-detect ─────────────────────────────────────
# In the image build the repo is already unpacked at the prefix; skip the
# self-copy then. Otherwise copy the linux/ tree, excluding local caches/venv.
if [ "$REPO_DIR" != "$ETHROX_DETECT_PREFIX" ]; then
    log "installing application to $ETHROX_DETECT_PREFIX"
    tar -C "$REPO_DIR" \
        --exclude=__pycache__ --exclude='*.pyc' --exclude=venv --exclude=.git \
        -cf - . | tar -C "$ETHROX_DETECT_PREFIX" -xf -
    if [ -f "$REPO_DIR/../version.json" ]; then
        install -m 0644 "$REPO_DIR/../version.json" "$ETHROX_DETECT_PREFIX/version.json"
    fi
else
    log "application already in place at $ETHROX_DETECT_PREFIX"
fi
chown -R "$ETHROX_DETECT_USER:$ETHROX_DETECT_USER" "$ETHROX_DETECT_PREFIX"

# ── 4. Python venv (isolated; rich only, no system-Python changes) ───────────
if [ ! -x "$ETHROX_DETECT_PREFIX/venv/bin/python" ]; then
    log "creating venv at $ETHROX_DETECT_PREFIX/venv"
    sudo -u "$ETHROX_DETECT_USER" python3 -m venv "$ETHROX_DETECT_PREFIX/venv"
fi
log "installing Python requirements into venv"
sudo -u "$ETHROX_DETECT_USER" "$ETHROX_DETECT_PREFIX/venv/bin/pip" install -q --upgrade pip
sudo -u "$ETHROX_DETECT_USER" "$ETHROX_DETECT_PREFIX/venv/bin/pip" install -q \
    -r "$ETHROX_DETECT_PREFIX/requirements.txt"

# ── 5. systemd units (system services, not --user) ───────────────────────────
log "installing systemd units"
install -m 0644 "$SCRIPT_DIR/ethrox-detect.service" \
    /etc/systemd/system/ethrox-detect.service
install -m 0644 "$SCRIPT_DIR/firstboot/ethrox-detect-firstboot.service" \
    /etc/systemd/system/ethrox-detect-firstboot.service
# Read-only-root hardening unit is installed but left DISABLED here — hand-installs
# stay writable. The image build enables it; operators opt in with:
#   sudo systemctl enable ethrox-detect-hardening.service && sudo reboot
install -m 0644 "$SCRIPT_DIR/durability/ethrox-detect-hardening.service" \
    /etc/systemd/system/ethrox-detect-hardening.service
systemctl daemon-reload

# ── 5b. SD-card durability baseline ──────────────────────────────────────────
apply_durability

if [ "$ENABLE_SERVICE" -eq 1 ]; then
    systemctl enable ethrox-detect.service
    systemctl enable ethrox-detect-firstboot.service
    log "services enabled (start on next boot / now via: systemctl start ethrox-detect)"
else
    log "services installed but not enabled (--no-enable)"
fi

log "appliance install complete."
log "  data dir : $ETHROX_DETECT_DATA_DIR"
log "  app dir  : $ETHROX_DETECT_PREFIX"
log "  service  : systemctl status ethrox-detect"
