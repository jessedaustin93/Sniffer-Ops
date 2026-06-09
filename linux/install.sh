#!/usr/bin/env bash
# SnifferOps Linux — installer
# Installs system deps, creates app menu entry, and installs the icon.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="com.snifferops.linux"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS_DIR="$HOME/.local/share/applications"
BIN_DIR="$HOME/.local/bin"

echo "[snifferops] Installing SnifferOps Linux Companion..."

# System packages
sudo apt-get install -y \
    python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
    libgtk-4-dev \
    rtl-sdr librtlsdr-dev \
    bluetooth bluez \
    network-manager 2>/dev/null || true

# Spy Agency fonts (shared with Windows companion)
FONT_DIR="$HOME/.local/share/fonts/snifferops"
mkdir -p "$FONT_DIR"
cp "$SCRIPT_DIR/assets/fonts/"*.ttf "$FONT_DIR/"
fc-cache -f "$FONT_DIR" 2>/dev/null || true
echo "[snifferops] Fonts installed to $FONT_DIR"

# Icon
mkdir -p "$ICON_DIR"
cp "$SCRIPT_DIR/assets/snifferops.svg" "$ICON_DIR/${APP_ID}.svg"
gtk-update-icon-cache ~/.local/share/icons/hicolor 2>/dev/null || true

# .desktop file
mkdir -p "$APPS_DIR"
sed "s|INSTALL_PATH|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/assets/snifferops.desktop" \
    > "$APPS_DIR/${APP_ID}.desktop"
chmod +x "$APPS_DIR/${APP_ID}.desktop"
update-desktop-database "$APPS_DIR" 2>/dev/null || true

# Optional: launcher in PATH
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/snifferops" << EOF
#!/usr/bin/env bash
exec python3 "$SCRIPT_DIR/snifferops_gui.py" "\$@"
EOF
chmod +x "$BIN_DIR/snifferops"

# GNOME autostart
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/${APP_ID}.desktop" << EOF
[Desktop Entry]
Type=Application
Name=SnifferOps
Comment=Wireless signal awareness hub
Exec=python3 $SCRIPT_DIR/snifferops_gui.py
Icon=${APP_ID}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF

# systemd user service (restarts on crash)
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/snifferops.service" << EOF
[Unit]
Description=SnifferOps Linux Companion
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=simple
ExecStart=python3 $SCRIPT_DIR/snifferops_gui.py
Restart=on-failure
RestartSec=10
Environment=WAYLAND_DISPLAY=wayland-0
Environment=GDK_BACKEND=wayland

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable snifferops.service 2>/dev/null || true

echo ""
echo "[snifferops] Done!"
echo "  App menu:  search for 'SnifferOps' in your GNOME app grid"
echo "  Terminal:  snifferops"
echo "  Direct:    python3 $SCRIPT_DIR/snifferops_gui.py"
