#!/usr/bin/env bash
# Ethrox Detect Linux — installer
# Installs system deps, creates app menu entry, and installs the icon.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="com.ethrox.detect.linux"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS_DIR="$HOME/.local/share/applications"
BIN_DIR="$HOME/.local/bin"

echo "[ethrox-detect] Installing Ethrox Detect Linux Companion..."

# System packages
sudo apt-get install -y \
    python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
    gir1.2-webkit-6.0 \
    libgtk-4-dev \
    rtl-sdr librtlsdr-dev \
    bluetooth bluez \
    network-manager wireless-tools 2>/dev/null || true

# Spy Agency fonts (shared with Windows companion)
FONT_DIR="$HOME/.local/share/fonts/ethrox-detect"
mkdir -p "$FONT_DIR"
cp "$SCRIPT_DIR/assets/fonts/"*.ttf "$FONT_DIR/"
fc-cache -f "$FONT_DIR" 2>/dev/null || true
echo "[ethrox-detect] Fonts installed to $FONT_DIR"

# Icon
mkdir -p "$ICON_DIR"
cp "$SCRIPT_DIR/assets/ethrox-detect.svg" "$ICON_DIR/${APP_ID}.svg"
gtk-update-icon-cache ~/.local/share/icons/hicolor 2>/dev/null || true

# .desktop file
mkdir -p "$APPS_DIR"
sed "s|INSTALL_PATH|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/assets/ethrox-detect.desktop" \
    > "$APPS_DIR/${APP_ID}.desktop"
chmod +x "$APPS_DIR/${APP_ID}.desktop"
update-desktop-database "$APPS_DIR" 2>/dev/null || true

# Optional: launcher in PATH
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/ethrox-detect" << EOF
#!/usr/bin/env bash
exec python3 "$SCRIPT_DIR/ethrox_detect_gui.py" "\$@"
EOF
chmod +x "$BIN_DIR/ethrox-detect"

# GNOME autostart
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/${APP_ID}.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Ethrox Detect
Comment=Wireless signal awareness hub
Exec=python3 $SCRIPT_DIR/ethrox_detect_gui.py
Icon=${APP_ID}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF

# systemd user service (restarts on crash)
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/ethrox-detect.service" << EOF
[Unit]
Description=Ethrox Detect Linux Companion
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=simple
ExecStart=python3 $SCRIPT_DIR/ethrox_detect_gui.py
Restart=on-failure
RestartSec=10
Environment=WAYLAND_DISPLAY=wayland-0
Environment=GDK_BACKEND=wayland

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable ethrox-detect.service 2>/dev/null || true

echo ""
echo "[ethrox-detect] Done!"
echo "  App menu:  search for 'Ethrox Detect' in your GNOME app grid"
echo "  Terminal:  ethrox-detect"
echo "  Direct:    python3 $SCRIPT_DIR/ethrox_detect_gui.py"
