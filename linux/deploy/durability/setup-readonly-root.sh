#!/usr/bin/env bash
# Ethrox Detect read-only-root hardening (Step 4).
#
# Design: the OS root is made read-only via the Raspberry Pi overlay filesystem
# (writes go to RAM, discarded on reboot — power loss can't corrupt the OS),
# while Ethrox Detect data lives on a SEPARATE writable partition mounted at
# /var/lib/ethrox-detect. A separate mount sits *over* the root overlay, so the DB,
# node_id, and config persist across reboots; SQLite WAL handles crash recovery
# on that partition.
#
# This runs ONCE (guarded), creates the data partition from the card's free
# space, migrates existing data, then enables the overlay and reboots. It is
# fail-safe: any error leaves the node in its previous (writable) state rather
# than a broken one, and it is idempotent.
#
# Only images built with read-only-root enabled ship the flag that arms this;
# hand-installs stay writable unless an operator opts in (see deploy/README.md).
set -uo pipefail

DATA_DIR="${ETHROX_DETECT_DATA_DIR:-/var/lib/ethrox-detect}"
DATA_LABEL="ethrox-detect-data"
SENTINEL="/var/lib/ethrox-detect/.readonly-provisioned"

log()  { printf '[ro-root] %s\n' "$*"; }
warn() { printf '[ro-root] WARN: %s\n' "$*" >&2; }
bail() { printf '[ro-root] ABORT: %s (leaving node writable)\n' "$*" >&2; exit 0; }

# Already done, or overlay already active → nothing to do.
[ -e "$SENTINEL" ] && { log "already hardened"; exit 0; }
if findmnt -no FSTYPE / | grep -q overlay; then
    log "root already an overlay; marking done"; touch "$SENTINEL" 2>/dev/null || true; exit 0
fi

command -v sfdisk   >/dev/null || bail "sfdisk missing"
command -v mkfs.ext4 >/dev/null || bail "mkfs.ext4 missing"

# ── Resolve the boot disk and partition names ────────────────────────────────
ROOT_SRC="$(findmnt -no SOURCE /)"                       # e.g. /dev/mmcblk0p2
case "$ROOT_SRC" in
    *[0-9]p[0-9]*) DISK="${ROOT_SRC%p[0-9]*}" ; PSEP="p" ;;  # mmcblk0p2 / nvme0n1p2
    *[0-9])        DISK="${ROOT_SRC%[0-9]*}"  ; PSEP=""  ;;  # sda2
    *) bail "cannot parse root device $ROOT_SRC" ;;
esac
log "root=$ROOT_SRC disk=$DISK"

# ── Reuse an existing data partition, else create one in free space ──────────
DATA_PART="$(blkid -L "$DATA_LABEL" 2>/dev/null || true)"
if [ -z "$DATA_PART" ]; then
    log "creating $DATA_LABEL partition in free space"
    # Append a Linux partition spanning the remaining space. Requires that the
    # image did NOT auto-expand root to fill the card (handled in the pi-gen
    # stage, which removes init_resize from cmdline).
    echo ',,L' | sfdisk --append "$DISK" || bail "sfdisk append failed"
    partprobe "$DISK" 2>/dev/null || true
    sleep 2
    # Highest-numbered partition is the one we just added.
    DATA_PART="$(lsblk -lnpo NAME "$DISK" | grep -E "${DISK}${PSEP}[0-9]+$" | sort -V | tail -1)"
    [ -n "$DATA_PART" ] || bail "could not locate new partition"
    mkfs.ext4 -F -L "$DATA_LABEL" "$DATA_PART" || bail "mkfs failed on $DATA_PART"
    log "formatted $DATA_PART as $DATA_LABEL"
fi

# ── Migrate existing data onto the partition and mount it ────────────────────
TMP_MNT="$(mktemp -d)"
mount "$DATA_PART" "$TMP_MNT" || bail "mount $DATA_PART failed"
if [ -d "$DATA_DIR" ] && [ -z "$(ls -A "$TMP_MNT" 2>/dev/null)" ]; then
    cp -a "$DATA_DIR/." "$TMP_MNT/" 2>/dev/null || warn "data copy incomplete"
fi
umount "$TMP_MNT" || true
rmdir "$TMP_MNT" 2>/dev/null || true

# fstab entry by label so it survives partition renumbering.
if ! grep -q "LABEL=$DATA_LABEL" /etc/fstab; then
    printf 'LABEL=%s\t%s\text4\tdefaults,noatime,nofail\t0\t2\n' \
        "$DATA_LABEL" "$DATA_DIR" >> /etc/fstab
fi
mount "$DATA_DIR" 2>/dev/null || mount "$DATA_PART" "$DATA_DIR" || bail "final mount failed"
log "data partition mounted at $DATA_DIR"

# ── Enable the read-only overlay + mark done, then reboot ────────────────────
touch "$SENTINEL" 2>/dev/null || true
if command -v raspi-config >/dev/null; then
    # enable_overlayfs makes / an overlay and /boot read-only.
    raspi-config nonint enable_overlayfs || bail "enable_overlayfs failed"
    log "overlay enabled; rebooting into read-only root"
    systemctl disable ethrox-detect-hardening.service 2>/dev/null || true
    systemctl reboot
else
    warn "raspi-config absent (non-RPi). Data partition is set up; configure"
    warn "overlayroot/ro-root per your distro. See deploy/README.md."
    systemctl disable ethrox-detect-hardening.service 2>/dev/null || true
fi
