#!/bin/bash -e
# pi-gen step: layer Ethrox Detect onto the Bookworm Lite rootfs.
#
# Runs in pi-gen host context with ${ROOTFS_DIR} and on_chroot available.
# ETHROX_DETECT_REPO must point at a checkout of the Ethrox Detect repo (CI sets it).

: "${ETHROX_DETECT_REPO:?set ETHROX_DETECT_REPO to the repo root}"

# 1. Place the linux/ tree at /opt/ethrox-detect inside the image.
install -d "${ROOTFS_DIR}/opt/ethrox-detect"
tar -C "${ETHROX_DETECT_REPO}/linux" \
    --exclude=__pycache__ --exclude='*.pyc' --exclude=venv --exclude=.git \
    -cf - . | tar -C "${ROOTFS_DIR}/opt/ethrox-detect" -xf -
install -m 0644 "${ETHROX_DETECT_REPO}/version.json" "${ROOTFS_DIR}/opt/ethrox-detect/version.json"

VERSION="$(sed -nE 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "${ETHROX_DETECT_REPO}/version.json")"
BUILD="$(sed -nE 's/^[[:space:]]*"build"[[:space:]]*:[[:space:]]*([0-9]+).*/\1/p' "${ETHROX_DETECT_REPO}/version.json")"
FULL_VERSION="$(sed -nE 's/^[[:space:]]*"full_version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "${ETHROX_DETECT_REPO}/version.json")"
if [ -z "${VERSION}" ] || [ -z "${BUILD}" ] || [ -z "${FULL_VERSION}" ]; then
    echo "Could not read version metadata from ${ETHROX_DETECT_REPO}/version.json" >&2
    exit 1
fi
GIT_COMMIT="$(git -C "${ETHROX_DETECT_REPO}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
install -d "${ROOTFS_DIR}/etc"
cat > "${ROOTFS_DIR}/etc/ethrox-detect-release" <<EOF
PRODUCT_NAME=Ethrox Detect
VERSION=${VERSION}
BUILD=${BUILD}
FULL_VERSION=${FULL_VERSION}
GIT_COMMIT=${GIT_COMMIT}
BUILD_DATE=${BUILD_DATE}
EOF

# 2. Run the appliance installer inside the chroot. Packages from 00-packages
#    are already present, so its apt step is a fast no-op; it creates the
#    service user, venv, udev rule, and enables the systemd units.
on_chroot << 'CHROOT'
set -e
# install-appliance.sh creates the user/venv/units and applies the journald
# durability baseline (apply_durability in lib-install.sh).
export ETHROX_DETECT_APPLIANCE_OFFLINE=1
/opt/ethrox-detect/deploy/install-appliance.sh

# ── Read-only-root (Step 4) ──────────────────────────────────────────────────
# Enable the one-shot hardening service: on first boot it carves a data
# partition from free space, moves /var/lib/ethrox-detect onto it, and turns on the
# Pi overlay filesystem (root read-only, writes to RAM). See
# deploy/durability/setup-readonly-root.sh.
systemctl enable ethrox-detect-hardening.service

# The hardening step needs free space for the data partition, so DO NOT let
# pi-gen's first-boot auto-resize expand root to fill the card. Remove the
# init_resize hook if present; root stays at its built size (read-only anyway).
if [ -f /boot/firmware/cmdline.txt ]; then
    sed -i 's# init=/usr/lib/raspberrypi-sys-mods/firstboot##; s# init=/usr/lib/raspi-config/init_resize\.sh##' /boot/firmware/cmdline.txt || true
fi
CHROOT
