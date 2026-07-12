#!/usr/bin/env bash
# Ethrox Detect first-boot provisioning. Runs once (guarded by a sentinel),
# then self-disables. Idempotent and safe to re-run if the sentinel is removed.
set -euo pipefail

PREFIX="${ETHROX_DETECT_PREFIX:-/opt/ethrox-detect}"
DATA_DIR="${ETHROX_DETECT_DATA_DIR:-/var/lib/ethrox-detect}"
USER_NAME="${ETHROX_DETECT_USER:-ethrox-detect}"
SENTINEL="$DATA_DIR/.provisioned"

log() { printf '[firstboot] %s\n' "$*"; }

if [ -e "$SENTINEL" ]; then
    log "already provisioned; nothing to do"
    exit 0
fi

install -d -o "$USER_NAME" -g "$USER_NAME" -m 0750 "$DATA_DIR"

# ── 1. Expand root filesystem to fill the SD card ────────────────────────────
# pi-gen images self-expand on first boot via init_resize; this is a fallback
# for other flashing paths.
if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_expand_rootfs || log "rootfs expand skipped/failed"
else
    log "raspi-config absent; skipping rootfs expand (assumed handled by image)"
fi

# ── 2. Generate stable node_id + default config.json ─────────────────────────
# Reuses the exact Step 2 logic so the id/config match what the hub expects.
sudo -u "$USER_NAME" env ETHROX_DETECT_DATA_DIR="$DATA_DIR" \
    "$PREFIX/venv/bin/python" -c \
    "import sys; sys.path.insert(0, '$PREFIX'); import paths; \
     print('node_id', paths.load_or_create_node_id()); paths.bootstrap_config()"

# ── 3. Hostname = ethrox-detect-<shortid> ───────────────────────────────────────
SHORTID="$(cut -c1-6 "$DATA_DIR/node_id")"
NEWHOST="ethrox-detect-$SHORTID"
if command -v hostnamectl >/dev/null 2>&1; then
    hostnamectl set-hostname "$NEWHOST"
else
    echo "$NEWHOST" > /etc/hostname
fi
# Keep /etc/hosts in sync so sudo/localhost resolution stays quiet.
if grep -qE '^127\.0\.1\.1' /etc/hosts; then
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$NEWHOST/" /etc/hosts
else
    printf '127.0.1.1\t%s\n' "$NEWHOST" >> /etc/hosts
fi
log "hostname set to $NEWHOST"

# ── 4. Wi-Fi baked credentials (Phase 1) ─────────────────────────────────────
# Look on the boot partition for a NetworkManager keyfile or wpa_supplicant.conf
# dropped at flash time, and move it into place.
for BOOT in /boot/firmware /boot; do
    [ -d "$BOOT" ] || continue
    if [ -f "$BOOT/ethrox-detect-wifi.nmconnection" ]; then
        install -d -m 0700 /etc/NetworkManager/system-connections
        install -m 0600 "$BOOT/ethrox-detect-wifi.nmconnection" \
            /etc/NetworkManager/system-connections/ethrox-detect-wifi.nmconnection
        rm -f "$BOOT/ethrox-detect-wifi.nmconnection"
        command -v nmcli >/dev/null 2>&1 && nmcli connection reload || true
        log "installed baked Wi-Fi NetworkManager profile"
        break
    fi
    if [ -f "$BOOT/wpa_supplicant.conf" ]; then
        install -m 0600 "$BOOT/wpa_supplicant.conf" \
            /etc/wpa_supplicant/wpa_supplicant.conf
        rm -f "$BOOT/wpa_supplicant.conf"
        log "installed baked wpa_supplicant.conf"
        break
    fi
done

# ── 5. Mark provisioned + self-disable ───────────────────────────────────────
touch "$SENTINEL"
chown "$USER_NAME:$USER_NAME" "$SENTINEL"
systemctl disable ethrox-detect-firstboot.service || true
log "provisioning complete"
