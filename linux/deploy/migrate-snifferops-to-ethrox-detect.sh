#!/usr/bin/env bash
set -euo pipefail

PRODUCT="Ethrox Detect"
OLD_SLUG="snifferops"
NEW_SLUG="ethrox-detect"
OLD_SERVICE="snifferops.service"
NEW_SERVICE="ethrox-detect.service"
APP_ID="com.ethrox.detect.linux"

HOME_DIR="${HOME:?HOME is required}"
STATE_DIR="${XDG_STATE_HOME:-$HOME_DIR/.local/state}/ethrox-detect"
BACKUP_ROOT="$STATE_DIR/migration-backups"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
SUMMARY="$STATE_DIR/migration-summary-$STAMP.txt"

OLD_DATA="$HOME_DIR/.snifferops"
NEW_DATA="$HOME_DIR/.ethrox-detect"
OLD_USER_SERVICE="$HOME_DIR/.config/systemd/user/$OLD_SERVICE"
NEW_USER_SERVICE="$HOME_DIR/.config/systemd/user/$NEW_SERVICE"
OLD_WANTS="$HOME_DIR/.config/systemd/user/default.target.wants/$OLD_SERVICE"
NEW_WANTS="$HOME_DIR/.config/systemd/user/default.target.wants/$NEW_SERVICE"
OLD_AUTOSTART="$HOME_DIR/.config/autostart/com.snifferops.linux.desktop"
NEW_AUTOSTART="$HOME_DIR/.config/autostart/$APP_ID.desktop"
OLD_DESKTOP="$HOME_DIR/.local/share/applications/com.snifferops.linux.desktop"
NEW_DESKTOP="$HOME_DIR/.local/share/applications/$APP_ID.desktop"
OLD_BIN="$HOME_DIR/.local/bin/snifferops"
NEW_BIN="$HOME_DIR/.local/bin/ethrox-detect"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINUX_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$LINUX_DIR/.." && pwd)"
INSTALL_DIR="${ETHROX_DETECT_INSTALL_DIR:-/opt/ethrox-detect}"
RUNTIME_DIR="$REPO_ROOT"
GUI_SCRIPT="$RUNTIME_DIR/linux/ethrox_detect_gui.py"
CLI_SCRIPT="$RUNTIME_DIR/linux/ethrox_detect_linux.py"

log() {
  printf '[ethrox-detect-migration] %s\n' "$*"
}

record() {
  printf '%s\n' "$*" | tee -a "$SUMMARY" >/dev/null
}

backup_path() {
  local path="$1"
  local label="$2"
  if [ -e "$path" ] || [ -L "$path" ]; then
    mkdir -p "$BACKUP_DIR/$label"
    cp -a "$path" "$BACKUP_DIR/$label/"
    record "Backed up $path -> $BACKUP_DIR/$label/"
  fi
}

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

install_runtime() {
  if command -v rsync >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    as_root install -d -o root -g root -m 0755 "$INSTALL_DIR"
    as_root rsync -a --delete \
      --exclude .git \
      --exclude .pytest_cache \
      --exclude tmp \
      --exclude '**/__pycache__' \
      "$REPO_ROOT/" "$INSTALL_DIR/"
    RUNTIME_DIR="$INSTALL_DIR"
    GUI_SCRIPT="$RUNTIME_DIR/linux/ethrox_detect_gui.py"
    CLI_SCRIPT="$RUNTIME_DIR/linux/ethrox_detect_linux.py"
    record "Installed runtime source to $INSTALL_DIR."
  else
    record "Using repository runtime path $REPO_ROOT; install rsync and sudo for /opt deployment."
  fi
}

stop_old_service() {
  if systemctl --user list-unit-files "$OLD_SERVICE" >/dev/null 2>&1 || [ -e "$OLD_USER_SERVICE" ]; then
    systemctl --user stop "$OLD_SERVICE" >/dev/null 2>&1 || true
    systemctl --user disable "$OLD_SERVICE" >/dev/null 2>&1 || true
    record "Stopped and disabled $OLD_SERVICE when present."
  else
    record "No user $OLD_SERVICE unit was registered."
  fi
}

migrate_data() {
  mkdir -p "$NEW_DATA"
  chmod 700 "$NEW_DATA"

  if [ -d "$OLD_DATA" ] && [ ! -L "$OLD_DATA" ]; then
    backup_path "$OLD_DATA" "data"
    shopt -s dotglob nullglob
    for item in "$OLD_DATA"/*; do
      local base
      base="$(basename "$item")"
      if [ ! -e "$NEW_DATA/$base" ]; then
        mv "$item" "$NEW_DATA/"
        record "Moved data item $base into $NEW_DATA."
      else
        record "Kept existing $NEW_DATA/$base; old copy remains in backup."
      fi
    done
    rmdir "$OLD_DATA" 2>/dev/null || true
    if [ ! -e "$OLD_DATA" ]; then
      ln -s "$NEW_DATA" "$OLD_DATA"
      record "Created temporary compatibility symlink $OLD_DATA -> $NEW_DATA."
    fi
  elif [ -L "$OLD_DATA" ]; then
    record "$OLD_DATA is already a symlink; leaving it in place."
  else
    record "No old data directory found at $OLD_DATA."
  fi
}

write_user_service() {
  mkdir -p "$(dirname "$NEW_USER_SERVICE")"
  cat > "$NEW_USER_SERVICE" <<EOF
[Unit]
Description=Ethrox Detect Linux Companion
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=simple
ExecStart=python3 $GUI_SCRIPT
Restart=on-failure
RestartSec=10
Environment=WAYLAND_DISPLAY=wayland-0
Environment=GDK_BACKEND=wayland
Environment=ETHROX_DETECT_DATA_DIR=$NEW_DATA

[Install]
WantedBy=default.target
EOF
  record "Installed $NEW_USER_SERVICE."
}

write_launchers() {
  mkdir -p "$HOME_DIR/.local/bin" "$(dirname "$NEW_AUTOSTART")" "$(dirname "$NEW_DESKTOP")"
  cat > "$NEW_BIN" <<EOF
#!/usr/bin/env bash
exec python3 "$GUI_SCRIPT" "\$@"
EOF
  chmod +x "$NEW_BIN"
  record "Installed CLI launcher $NEW_BIN."

  cat > "$NEW_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Ethrox Detect
Comment=Passive local awareness hub
Exec=python3 $GUI_SCRIPT
Icon=$APP_ID
Terminal=false
Categories=Utility;Network;
StartupWMClass=ethrox-detect
EOF
  cp -a "$NEW_DESKTOP" "$NEW_AUTOSTART"
  record "Installed desktop launcher $NEW_DESKTOP."
  record "Installed autostart launcher $NEW_AUTOSTART."
}

remove_old_launchers() {
  backup_path "$OLD_USER_SERVICE" "service"
  backup_path "$OLD_WANTS" "service-wants"
  backup_path "$OLD_AUTOSTART" "autostart"
  backup_path "$OLD_DESKTOP" "desktop"
  backup_path "$OLD_BIN" "bin"

  rm -f "$OLD_USER_SERVICE" "$OLD_WANTS" "$OLD_AUTOSTART" "$OLD_DESKTOP" "$OLD_BIN"
  record "Removed old user service and launchers when present."
}

run_self_tests() {
  if python3 "$CLI_SCRIPT" --version >/dev/null; then
    record "Version self-test passed."
  else
    record "Version self-test failed."
    return 1
  fi

  systemctl --user daemon-reload >/dev/null 2>&1 || true
  systemctl --user enable "$NEW_SERVICE" >/dev/null 2>&1 || true
  systemctl --user start "$NEW_SERVICE" >/dev/null 2>&1 || true
  sleep 2

  if systemctl --user is-active "$NEW_SERVICE" >/dev/null 2>&1; then
    record "$NEW_SERVICE is active."
  else
    record "$NEW_SERVICE is not active; inspect with: systemctl --user status $NEW_SERVICE"
  fi

  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 3 http://127.0.0.1:8766/ethrox-detect/health >/dev/null 2>&1; then
      record "API health check passed at /ethrox-detect/health."
    else
      record "API health check did not respond; service may need a graphical session or scanner dependency."
    fi
  fi
}

write_rollback() {
  cat >> "$SUMMARY" <<EOF

Rollback:
  systemctl --user stop $NEW_SERVICE || true
  systemctl --user disable $NEW_SERVICE || true
  rm -f "$NEW_USER_SERVICE" "$NEW_WANTS" "$NEW_AUTOSTART" "$NEW_DESKTOP" "$NEW_BIN"
  rm -rf "$NEW_DATA"
  cp -a "$BACKUP_DIR/data/$(basename "$OLD_DATA")" "$OLD_DATA" 2>/dev/null || true
  cp -a "$BACKUP_DIR/service/$(basename "$OLD_USER_SERVICE")" "$OLD_USER_SERVICE" 2>/dev/null || true
  systemctl --user daemon-reload
  systemctl --user enable --now $OLD_SERVICE 2>/dev/null || true

Backups are retained at:
  $BACKUP_DIR
EOF
}

main() {
  mkdir -p "$BACKUP_DIR" "$STATE_DIR"
  : > "$SUMMARY"
  record "$PRODUCT local migration started at $STAMP."
  record "Repository Linux path: $LINUX_DIR"
  record "No private file contents are written to this summary."

  install_runtime
  stop_old_service
  migrate_data
  write_user_service
  write_launchers
  remove_old_launchers
  run_self_tests || true
  write_rollback

  log "Migration summary: $SUMMARY"
  log "Backup directory: $BACKUP_DIR"
  log "Run validation:"
  log "  systemctl --user status $NEW_SERVICE"
  log "  curl -fsS http://127.0.0.1:8766/ethrox-detect/health"
}

main "$@"
