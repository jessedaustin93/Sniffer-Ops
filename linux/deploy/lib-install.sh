# shellcheck shell=bash
# SnifferOps — shared installer functions, sourced by both the desktop
# (install.sh) and appliance (deploy/install-appliance.sh) installers.
#
# This file is meant to be sourced, not executed. It defines helpers only.

# ── Constants ─────────────────────────────────────────────────────────────────
SNIFFEROPS_USER="${SNIFFEROPS_USER:-snifferops}"
SNIFFEROPS_PREFIX="${SNIFFEROPS_PREFIX:-/opt/snifferops}"
SNIFFEROPS_DATA_DIR="${SNIFFEROPS_DATA_DIR:-/var/lib/snifferops}"

# ── Logging ───────────────────────────────────────────────────────────────────
log()  { printf '[snifferops] %s\n' "$*"; }
warn() { printf '[snifferops] WARN: %s\n' "$*" >&2; }
die()  { printf '[snifferops] ERROR: %s\n' "$*" >&2; exit 1; }

require_root() {
    [ "$(id -u)" -eq 0 ] || die "must run as root (use sudo)"
}

# ── apt ───────────────────────────────────────────────────────────────────────
# apt_install pkg...  — non-interactive, fails loudly (no silent || true mask).
apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
}

# ── Service user ──────────────────────────────────────────────────────────────
# ensure_system_user <name> <home>  — idempotent system user with nologin shell.
ensure_system_user() {
    local name="$1" home="$2"
    if id "$name" >/dev/null 2>&1; then
        log "user $name already exists"
    else
        useradd --system --home-dir "$home" --create-home \
                --shell /usr/sbin/nologin "$name"
        log "created system user $name"
    fi
}

# add_user_groups <user> <group>...  — add to each group that exists.
add_user_groups() {
    local user="$1"; shift
    local g
    for g in "$@"; do
        if getent group "$g" >/dev/null 2>&1; then
            usermod -aG "$g" "$user"
            log "added $user to group $g"
        else
            warn "group $g not present; skipping (device access may need it)"
        fi
    done
}

# ── Directories ───────────────────────────────────────────────────────────────
# ensure_dir <path> <owner> <mode>
ensure_dir() {
    install -d -o "$2" -g "$2" -m "$3" "$1"
}

# ── RTL-SDR udev ──────────────────────────────────────────────────────────────
# The rtl-sdr package ships udev rules, but they are not guaranteed to grant
# group access under a service user. This rule makes RTL2832U dongles readable
# by the plugdev group without root.
install_rtlsdr_udev() {
    local rule=/etc/udev/rules.d/60-snifferops-rtlsdr.rules
    install -m 0644 /dev/stdin "$rule" <<'EOF'
# SnifferOps: RTL2832U-based RTL-SDR dongles accessible to the plugdev group
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0660", GROUP="plugdev"
EOF
    log "installed RTL-SDR udev rule at $rule"
    # Reload rules when udev is live (not in an image-build chroot).
    if command -v udevadm >/dev/null 2>&1 && [ -d /run/udev ]; then
        udevadm control --reload-rules && udevadm trigger || \
            warn "udevadm reload failed (fine inside a build chroot)"
    fi
}

# ── Spy Agency fonts (desktop only) ───────────────────────────────────────────
# copy_fonts <repo_dir> <target_font_dir>
copy_fonts() {
    local repo="$1" dest="$2"
    if [ -d "$repo/assets/fonts" ]; then
        install -d "$dest"
        install -m 0644 "$repo/assets/fonts/"*.ttf "$dest/" 2>/dev/null || \
            warn "no .ttf fonts found in $repo/assets/fonts"
        command -v fc-cache >/dev/null 2>&1 && fc-cache -f "$dest" >/dev/null 2>&1 || true
        log "fonts installed to $dest"
    fi
}
