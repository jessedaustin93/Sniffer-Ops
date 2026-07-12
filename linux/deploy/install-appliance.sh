#!/usr/bin/env bash
# SnifferOps — headless appliance installer.
#
# Turns a clean Debian/Raspberry Pi OS Lite (Bookworm) system into a
# "SnifferOps only" node: no GTK, installed under /opt/snifferops, run by a
# dedicated `snifferops` system user via a system systemd service.
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
ensure_system_user "$SNIFFEROPS_USER" "$SNIFFEROPS_DATA_DIR"
# Hardware access for BlueZ / NetworkManager / RTL-SDR under the service user.
add_user_groups "$SNIFFEROPS_USER" bluetooth netdev plugdev dialout
install_rtlsdr_udev

ensure_dir "$SNIFFEROPS_PREFIX" "$SNIFFEROPS_USER" 0755
ensure_dir "$SNIFFEROPS_DATA_DIR" "$SNIFFEROPS_USER" 0750

# ── 3. Copy the app into /opt/snifferops ─────────────────────────────────────
# In the image build the repo is already unpacked at the prefix; skip the
# self-copy then. Otherwise copy the linux/ tree, excluding local caches/venv.
if [ "$REPO_DIR" != "$SNIFFEROPS_PREFIX" ]; then
    log "installing application to $SNIFFEROPS_PREFIX"
    tar -C "$REPO_DIR" \
        --exclude=__pycache__ --exclude='*.pyc' --exclude=venv --exclude=.git \
        -cf - . | tar -C "$SNIFFEROPS_PREFIX" -xf -
else
    log "application already in place at $SNIFFEROPS_PREFIX"
fi
chown -R "$SNIFFEROPS_USER:$SNIFFEROPS_USER" "$SNIFFEROPS_PREFIX"

# ── 4. Python venv (isolated; rich only, no system-Python changes) ───────────
if [ ! -x "$SNIFFEROPS_PREFIX/venv/bin/python" ]; then
    log "creating venv at $SNIFFEROPS_PREFIX/venv"
    sudo -u "$SNIFFEROPS_USER" python3 -m venv "$SNIFFEROPS_PREFIX/venv"
fi
log "installing Python requirements into venv"
sudo -u "$SNIFFEROPS_USER" "$SNIFFEROPS_PREFIX/venv/bin/pip" install -q --upgrade pip
sudo -u "$SNIFFEROPS_USER" "$SNIFFEROPS_PREFIX/venv/bin/pip" install -q \
    -r "$SNIFFEROPS_PREFIX/requirements.txt"

# ── 5. systemd units (system services, not --user) ───────────────────────────
log "installing systemd units"
install -m 0644 "$SCRIPT_DIR/snifferops.service" \
    /etc/systemd/system/snifferops.service
install -m 0644 "$SCRIPT_DIR/firstboot/snifferops-firstboot.service" \
    /etc/systemd/system/snifferops-firstboot.service
systemctl daemon-reload

if [ "$ENABLE_SERVICE" -eq 1 ]; then
    systemctl enable snifferops.service
    systemctl enable snifferops-firstboot.service
    log "services enabled (start on next boot / now via: systemctl start snifferops)"
else
    log "services installed but not enabled (--no-enable)"
fi

log "appliance install complete."
log "  data dir : $SNIFFEROPS_DATA_DIR"
log "  app dir  : $SNIFFEROPS_PREFIX"
log "  service  : systemctl status snifferops"
