#!/bin/bash -e
# pi-gen step: layer SnifferOps onto the Bookworm Lite rootfs.
#
# Runs in pi-gen host context with ${ROOTFS_DIR} and on_chroot available.
# SNIFFEROPS_REPO must point at a checkout of the Sniffer-Ops repo (CI sets it).

: "${SNIFFEROPS_REPO:?set SNIFFEROPS_REPO to the repo root}"

# 1. Place the linux/ tree at /opt/snifferops inside the image.
install -d "${ROOTFS_DIR}/opt/snifferops"
tar -C "${SNIFFEROPS_REPO}/linux" \
    --exclude=__pycache__ --exclude='*.pyc' --exclude=venv --exclude=.git \
    -cf - . | tar -C "${ROOTFS_DIR}/opt/snifferops" -xf -

# 2. Run the appliance installer inside the chroot. Packages from 00-packages
#    are already present, so its apt step is a fast no-op; it creates the
#    service user, venv, udev rule, and enables the systemd units.
on_chroot << 'CHROOT'
set -e
# install-appliance.sh creates the user/venv/units and applies the journald
# durability baseline (apply_durability in lib-install.sh).
/opt/snifferops/deploy/install-appliance.sh

# Stamp provenance.
install -d /etc
cp /opt/snifferops/VERSION /etc/snifferops-version 2>/dev/null || true
CHROOT
