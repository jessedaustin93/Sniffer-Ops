#!/usr/bin/env python3
"""
SnifferOps Linux — GTK4 GUI matching the Windows/Android tactical dark theme.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, GObject, Pango, Gdk
import cairo
import math
import os
import platform
import socket
import sys
import threading
import time
import uuid

import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import awareness_log
import signal_classifier
from lenses.all_lenses import route
from sync.node_sync import NodeSyncManager, check_peer_health

DATA_DIR  = os.path.expanduser("~/.snifferops")
LOG_PATH  = os.path.join(DATA_DIR, "awareness.json")
CFG_PATH  = os.path.join(DATA_DIR, "config.json")
NODE_ID   = str(uuid.uuid4())[:16]
NODE_NAME = f"linux-{platform.node()}"

_scan_stats: dict = {"wifi": 0, "bt": 0, "sdr": 0, "syncs": 0, "alerts": 0}
_sync_manager: NodeSyncManager | None = None
_scan_active = False


# ── Theme colours (matching Windows/Android palette exactly) ─────────────────

C = {
    "bg":           "#020617",
    "panel":        "#111827",
    "panel2":       "#0B1120",
    "surface":      "#0F172A",
    "border":       "#255866",
    "border_green": "#0B6B57",
    "text":         "#E5E7EB",
    "muted":        "#9CA3AF",
    "dim":          "#6B7280",
    "green":        "#21F982",
    "green2":       "#10B981",
    "blue":         "#00BFFF",
    "blue2":        "#0D84FF",
    "orange":       "#F59E0B",
    "purple":       "#8B5CF6",
    "pink":         "#EC4899",
    "red":          "#EF4444",
    "cyan":         "#22D3EE",
    "wifi":         "#39FF14",
    "bt":           "#00BFFF",
    "cell":         "#F59E0B",
    "sdr":          "#8B5CF6",
}

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FONTS_DIR  = os.path.join(_SCRIPT_DIR, "assets", "fonts")


def _load_bundled_fonts() -> bool:
    """Register the bundled TTF files with fontconfig at runtime so GTK can
    resolve 'Spy Agency …' by name without a prior fc-cache run.
    Returns True if the fonts were registered successfully."""
    import ctypes, ctypes.util, shutil
    fc_paths = [
        ctypes.util.find_library("fontconfig"),
        "libfontconfig.so.1",
        "libfontconfig.so",
    ]
    lib = None
    for p in fc_paths:
        if p:
            try:
                lib = ctypes.CDLL(p)
                break
            except OSError:
                continue
    if lib is None:
        return False
    try:
        lib.FcConfigAppFontAddDir.restype  = ctypes.c_bool
        lib.FcConfigAppFontAddDir.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        ok = lib.FcConfigAppFontAddDir(None, _FONTS_DIR.encode())
        return bool(ok)
    except Exception:
        return False


def _build_css() -> str:
    """Build the GTK4 CSS string.  Font families are resolved by name after
    _load_bundled_fonts() has registered them with fontconfig."""
    have_fonts = _load_bundled_fonts()

    if have_fonts:
        font_body  = "Spy Agency Italic"
        font_cond  = "Spy Agency Condensed"
        font_title = "Spy Agency Gradient Italic"
    else:
        font_body  = "Ubuntu Mono, DejaVu Sans Mono, Courier New, monospace"
        font_cond  = font_body
        font_title = font_body

    return f"""
* {{
    font-family: "{font_body}";
    color: {C['text']};
}}
label, button > label, entry, textview, columnview, listview,
headerbar label, viewswitcherbar label {{
    font-family: "{font_body}";
}}
.title-font  {{ font-family: "{font_title}"; }}
.cond-font   {{ font-family: "{font_cond}";  }}
window, .main-window {{
    background-color: {C['bg']};
    background-image: url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='28' height='28'><line x1='0' y1='0' x2='28' y2='0' stroke='%230B3A35' stroke-width='0.45'/><line x1='0' y1='0' x2='0' y2='28' stroke='%230B3A35' stroke-width='0.45'/></svg>");
    background-repeat: repeat;
}}
headerbar {{
    background-color: #000000;
    border-bottom: 1px solid {C['border_green']};
    min-height: 52px;
}}
headerbar * {{
    color: {C['text']};
}}
.title-green {{
    color: {C['green']};
    font-weight: bold;
    font-size: 28px;
    letter-spacing: 3px;
    font-family: "{font_title}";
}}
.subtitle-muted {{
    color: #637082;
    font-size: 14px;
    letter-spacing: 2px;
    font-family: "{font_body}";
}}
.panel {{
    background-color: {C['panel']};
    border: 1px solid {C['border']};
    border-radius: 6px;
}}
.panel-green {{
    background-color: rgba(2,6,23,0.85);
    border: 1px solid {C['border_green']};
    border-radius: 7px;
}}
.panel-dark {{
    background-color: {C['panel2']};
    border: 1px solid {C['border']};
    border-radius: 6px;
}}
.section-label {{
    color: {C['muted']};
    font-size: 12px;
    letter-spacing: 2px;
    font-weight: bold;
    font-family: "{font_cond}";
}}
.tile-count-green  {{ color: {C['wifi']};   font-size: 28px; font-weight: bold; font-family: "{font_body}"; }}
.tile-count-blue   {{ color: {C['bt']};     font-size: 28px; font-weight: bold; font-family: "{font_body}"; }}
.tile-count-pink   {{ color: {C['pink']};   font-size: 28px; font-weight: bold; font-family: "{font_body}"; }}
.tile-count-orange {{ color: {C['orange']}; font-size: 28px; font-weight: bold; font-family: "{font_body}"; }}
.tile-count-purple {{ color: {C['purple']}; font-size: 28px; font-weight: bold; font-family: "{font_body}"; }}
.tile-count-red    {{ color: {C['red']};    font-size: 28px; font-weight: bold; font-family: "{font_body}"; }}
.tile-label {{ color: {C['muted']}; font-size: 12px; letter-spacing: 1px; font-family: "{font_body}"; }}
.tile-sub   {{ color: {C['dim']};   font-size: 11px; font-family: "{font_cond}"; }}
.stat-label {{ color: {C['muted']}; font-size: 13px; }}
.stat-green  {{ color: {C['wifi']};   font-size: 16px; font-weight: bold; }}
.stat-blue   {{ color: {C['bt']};     font-size: 16px; font-weight: bold; }}
.stat-orange {{ color: {C['orange']}; font-size: 16px; font-weight: bold; }}
.stat-purple {{ color: {C['purple']}; font-size: 16px; font-weight: bold; }}
.stat-red    {{ color: {C['red']};    font-size: 16px; font-weight: bold; }}
.btn-scan-start {{
    background: linear-gradient({C['blue2']}, #0B4FA4);
    color: white;
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 2px;
    border: 1px solid {C['cyan']};
    border-radius: 6px;
    min-height: 52px;
}}
.btn-scan-stop {{
    background: linear-gradient({C['red']}, #7F0000);
    color: white;
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 2px;
    border: 1px solid #FF7A7A;
    border-radius: 6px;
    min-height: 52px;
}}
.btn-secondary {{
    background-color: {C['panel']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    font-weight: bold;
}}
.awareness-title {{
    color: {C['cyan']};
    font-size: 13px;
    font-weight: bold;
    letter-spacing: 1px;
}}
.awareness-summary {{
    color: {C['text']};
    font-size: 18px;
    font-weight: bold;
}}
.awareness-detail {{
    color: {C['green2']};
    font-size: 12px;
}}
.awareness-odd {{
    color: {C['orange']};
    font-size: 12px;
}}
.awareness-hint {{
    color: {C['muted']};
    font-size: 11px;
}}
.sdr-online {{
    color: {C['green']};
    font-size: 13px;
    font-weight: bold;
    letter-spacing: 1px;
}}
.sdr-offline {{
    color: {C['muted']};
    font-size: 13px;
    font-weight: bold;
    letter-spacing: 1px;
}}
.sdr-sub {{
    color: rgba(150,163,175,0.76);
    font-size: 11px;
}}
.endpoint-label {{
    color: {C['cyan']};
    font-size: 16px;
    font-weight: bold;
}}
columnview, listview {{
    background-color: {C['panel2']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    font-size: 12px;
}}
columnview > header > button {{
    background-color: {C['panel']};
    color: {C['muted']};
    border-bottom: 1px solid {C['border']};
    font-size: 11px;
    letter-spacing: 1px;
    font-weight: bold;
}}
columnview row:nth-child(odd)  {{ background-color: {C['panel2']}; }}
columnview row:nth-child(even) {{ background-color: {C['surface']}; }}
columnview row:hover  {{ background-color: rgba(37,88,102,0.4); }}
scrollbar {{ background-color: {C['panel']}; }}
scrollbar slider {{ background-color: {C['border']}; min-width: 6px; min-height: 6px; }}
entry, .entry {{ background-color: {C['panel2']}; color: {C['green']}; border: 1px solid {C['border']}; caret-color: {C['green']}; }}
.log-box {{
    background-color: {C['panel2']};
    color: #D1D5DB;
    border: 1px solid #374151;
    font-size: 12px;
    font-family: "{font_cond}";
}}
.peer-online  {{ color: {C['green']}; }}
.peer-offline {{ color: {C['red']};   }}
.threat-alert {{ color: {C['red']};    font-weight: bold; }}
.threat-watch {{ color: {C['orange']}; font-weight: bold; }}
.threat-safe  {{ color: {C['green2']}; }}
viewswitcherbar {{
    background-color: #000000;
    border-top: 1px solid {C['border_green']};
}}
viewswitcherbar button {{
    color: {C['muted']};
    font-size: 11px;
}}
viewswitcherbar button:checked {{
    color: {C['green']};
}}
.tile-btn {{
    background-color: {C['panel']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 0;
    margin: 3px;
}}
.tile-btn:hover {{
    background-color: #1a2840;
    border-color: {C['green']};
}}
.tile-btn:active {{
    background-color: {C['surface']};
}}
.tile-btn-disabled {{
    background-color: {C['panel']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 0;
    margin: 3px;
    opacity: 0.65;
}}
"""


# ── Config ────────────────────────────────────────────────────────────────────

def _tailscale_ip() -> str:
    """Return this machine's Tailscale IPv4 (100.x.x.x) or empty string."""
    try:
        r = subprocess.run(["tailscale", "ip", "-4"],
                           capture_output=True, text=True, timeout=4)
        return r.stdout.strip()
    except Exception:
        return ""


def _tailscale_nodes() -> list[dict]:
    """Return list of {name, ip, os} for all online Tailscale peers."""
    try:
        r = subprocess.run(["tailscale", "status", "--json"],
                           capture_output=True, text=True, timeout=5)
        data = json.loads(r.stdout)
        nodes = []
        for v in data.get("Peer", {}).values():
            if not v.get("Online"):
                continue
            ips = v.get("TailscaleIPs", [])
            ip4 = next((x for x in ips if "." in x), None)
            if ip4:
                nodes.append({
                    "name": v.get("HostName", ip4),
                    "ip":   ip4,
                    "os":   v.get("OS", ""),
                })
        return nodes
    except Exception:
        return []


def load_config() -> dict:
    import json
    try:
        with open(CFG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"port": 8765, "bind": "0.0.0.0",
                "wifi": True, "bluetooth": True, "sdr": False,
                "sdr_remote": "", "peers": []}


def save_config(cfg: dict) -> None:
    import json
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CFG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Scanner callbacks ─────────────────────────────────────────────────────────

def _submit(signals: list[dict], signal_type: str) -> None:
    snapshot = {
        "schema": 1, "nodeId": NODE_ID, "nodeName": NODE_NAME,
        "capturedAt": int(time.time() * 1000),
        "location": {}, "completeTypes": [signal_type], "signals": signals,
    }
    awareness_log.merge_snapshot(snapshot)
    _scan_stats["syncs"] += 1


def _on_wifi(signals: list[dict]) -> None:
    for s in signals:
        s["deviceClass"] = signal_classifier.classify_wifi(s).specific_type
    _submit(signals, "WIFI")
    _scan_stats["wifi"] += len(signals)


def _on_bt(devices: list[dict]) -> None:
    for d in devices:
        d["deviceClass"] = signal_classifier.classify_bluetooth(d).specific_type
    _submit(devices, "BLUETOOTH")
    _scan_stats["bt"] += len(devices)


def _on_sdr(signals: list[dict]) -> None:
    for s in signals:
        freq = s.get("frequencyHz") or 0
        s["deviceClass"] = signal_classifier.classify_sdr(freq).specific_type
        d = route(freq)
        if d:
            s["notes"] = f"Lens: {d.kind}/{d.mode or d.title}"
    _submit(signals, "RTL_SDR")
    _scan_stats["sdr"] += len(signals)


# ── Radar drawing area ────────────────────────────────────────────────────────

class RadarWidget(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(154, 154)
        self.set_draw_func(self._draw)
        self._angle = 0.0
        self._active = False
        GLib.timeout_add(50, self._tick)

    def set_active(self, active: bool) -> None:
        self._active = active

    def _tick(self) -> bool:
        if self._active:
            self._angle = (self._angle + 6) % 360
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, area, cr: cairo.Context, w: int, h: int) -> None:
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 2

        # Background circle
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source_rgb(0.02, 0.06, 0.047)
        cr.fill_preserve()
        cr.set_source_rgba(0.13, 0.77, 0.51, 0.95)
        cr.set_line_width(2.2)
        cr.stroke()

        # Rings
        for radius, alpha in [(r * 0.70, 0.30), (r * 0.42, 0.22)]:
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.set_source_rgba(0.13, 0.77, 0.51, alpha)
            cr.set_line_width(1.0)
            cr.stroke()

        # Crosshairs
        cr.set_source_rgba(0.12, 0.86, 0.45, 0.38)
        cr.set_line_width(0.9)
        cr.move_to(cx, cy - r + 4); cr.line_to(cx, cy + r - 4); cr.stroke()
        cr.move_to(cx - r + 4, cy); cr.line_to(cx + r - 4, cy); cr.stroke()

        # Sweep
        if self._active:
            a_rad = math.radians(self._angle - 90)
            sweep = math.radians(45)
            cr.move_to(cx, cy)
            cr.arc(cx, cy, r - 2, a_rad - sweep, a_rad)
            cr.close_path()
            pat = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
            pat.add_color_stop_rgba(0, 0.13, 1.0, 0.5, 0.5)
            pat.add_color_stop_rgba(1, 0.13, 1.0, 0.5, 0.0)
            cr.set_source(pat)
            cr.fill()

        # Centre dot
        cr.arc(cx, cy, 4.5, 0, 2 * math.pi)
        cr.set_source_rgb(0.13, 0.99, 0.51)
        cr.fill()

        # LIVE / IDLE text
        cr.set_font_size(13)
        cr.set_font_face(cairo.ToyFontFace("Monospace", cairo.FontSlant.NORMAL,
                                           cairo.FontWeight.BOLD))
        label = "LIVE" if self._active else "IDLE"
        label_r, label_g, label_b = (0.13, 0.99, 0.51) if self._active else (0.61, 0.64, 0.67)
        ext = cr.text_extents(label)
        cr.move_to(cx - ext.width / 2, cy + r * 0.65 + ext.height / 2)
        cr.set_source_rgb(label_r, label_g, label_b)
        cr.show_text(label)


# ── GObject row model ─────────────────────────────────────────────────────────

class SignalRow(GObject.Object):
    __gtype_name__ = "SnifferSignalRow"
    sig_type = GObject.Property(type=str, default="")
    name     = GObject.Property(type=str, default="")
    address  = GObject.Property(type=str, default="")
    strength = GObject.Property(type=str, default="")
    cls      = GObject.Property(type=str, default="")
    threat   = GObject.Property(type=str, default="")
    details  = GObject.Property(type=str, default="")

    def __init__(self, row: dict):
        super().__init__()
        self.sig_type = str(row.get("Type") or "")
        self.name     = str(row.get("Signal") or "")
        self.address  = str(row.get("AddressOrFrequency") or "")
        self.strength = str(row.get("StrengthOrPower") or "")
        self.cls      = str(row.get("Classification") or "")
        self.threat   = str(row.get("Confidence") or "UNKNOWN")
        self.details  = str(row.get("Details") or "")


# ── Helper widgets ────────────────────────────────────────────────────────────

def _label(text: str, css: str = "", markup: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(xalign=0)
    if markup:
        lbl.set_markup(text)
    else:
        lbl.set_text(text)
    if css:
        lbl.add_css_class(css)
    return lbl


def _scanner_tile(count_css: str, label: str, sub: str,
                  navigable: bool = True) -> tuple[Gtk.Button, Gtk.Label]:
    """Returns (button, count_label) for a scanner tile."""
    btn = Gtk.Button()
    btn.add_css_class("tile-btn" if navigable else "tile-btn-disabled")
    btn.set_hexpand(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.set_margin_top(10)
    box.set_margin_bottom(10)
    btn.set_child(box)

    count_lbl = _label("0", count_css)
    box.append(count_lbl)
    box.append(_label(label, "tile-label"))
    box.append(_label(sub,   "tile-sub"))
    return btn, count_lbl


def _stat_row(dot_colour: str, label: str,
              count_css: str) -> tuple[Gtk.Box, Gtk.Label]:
    """Returns (row_box, count_label)."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    dot = Gtk.Label()
    dot.set_markup(f'<span foreground="{dot_colour}" size="small">●</span>')
    row.append(dot)
    lbl = _label(label, "stat-label")
    lbl.set_size_request(72, -1)
    row.append(lbl)
    cnt = _label("0", count_css)
    row.append(cnt)
    return row, cnt


def _make_signal_table(filter_type: str | None = None) -> tuple[Gtk.ScrolledWindow, Gio.ListStore]:
    store = Gio.ListStore(item_type=SignalRow)
    filter_model = Gtk.FilterListModel(model=store)

    if filter_type:
        expr = Gtk.PropertyExpression.new(SignalRow, None, "sig_type")
        sf = Gtk.StringFilter(expression=expr)
        sf.set_search(filter_type)
        sf.set_match_mode(Gtk.StringFilterMatchMode.EXACT)
        filter_model.set_filter(sf)

    cv = Gtk.ColumnView(
        model=Gtk.NoSelection(model=filter_model),
        show_row_separators=True,
        show_column_separators=False,
        vexpand=True, hexpand=True,
    )

    def _add(title, prop, width, expand=False):
        factory = Gtk.SignalListItemFactory()
        def _setup(_f, item):
            lbl = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
            lbl.set_margin_start(6); lbl.set_margin_end(6)
            lbl.set_margin_top(3); lbl.set_margin_bottom(3)
            item.set_child(lbl)
        def _bind(_f, item, p=prop):
            row: SignalRow = item.get_item()
            lbl: Gtk.Label = item.get_child()
            val = row.get_property(p)
            if p == "threat":
                classes = {"ALERT": "threat-alert", "SUSPICIOUS": "threat-watch",
                           "WATCH": "threat-watch", "SAFE": "threat-safe"}
                cls = classes.get(val.upper(), "")
                lbl.set_text(val)
                for c in ["threat-alert", "threat-watch", "threat-safe"]:
                    lbl.remove_css_class(c)
                if cls:
                    lbl.add_css_class(cls)
            else:
                lbl.set_text(val)
        factory.connect("setup", _setup)
        factory.connect("bind", _bind)
        col = Gtk.ColumnViewColumn(title=title, factory=factory,
                                   fixed_width=width, expand=expand)
        cv.append_column(col)

    _add("Signal",     "name",     220, True)
    _add("Addr/Freq",  "address",  180)
    _add("dBm",        "strength",  60)
    _add("Class",      "cls",      200, True)
    _add("Threat",     "threat",    80)
    _add("Details",    "details",  260, True)

    sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    sw.set_child(cv)
    return sw, store


# ── Main window ───────────────────────────────────────────────────────────────

class SnifferOpsWindow(Adw.ApplicationWindow):

    def __init__(self, app: "SnifferOpsApp"):
        super().__init__(application=app)
        self.set_title("SnifferOps")
        self.set_default_size(1280, 860)
        self.add_css_class("main-window")

        self._cfg = load_config()
        self._all_store = Gio.ListStore(item_type=SignalRow)
        self._peer_status_labels: list[Gtk.Label] = []
        self._peer_online: list[bool] = []

        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)

        tv = Adw.ToolbarView()
        self._toast.set_child(tv)

        # ── Header bar ────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        tv.add_top_bar(header)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        t1 = _label("SNIFFER OPS", "title-green")
        t1.set_halign(Gtk.Align.START)
        t2 = _label("LINUX COMPANION", "subtitle-muted")
        t2.set_halign(Gtk.Align.START)
        title_box.append(t1)
        title_box.append(t2)
        header.set_title_widget(title_box)

        self._refresh_btn = Gtk.Button(label="REFRESH")
        self._refresh_btn.add_css_class("btn-secondary")
        self._refresh_btn.connect("clicked", self._on_refresh)
        header.pack_end(self._refresh_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.add_css_class("flat")
        m = Gio.Menu()
        m.append("About", "app.about")
        m.append("Quit",  "app.quit")
        menu_btn.set_menu_model(m)
        header.pack_end(menu_btn)

        # ── View stack ────────────────────────────────────────────────────
        self._stack = Adw.ViewStack()
        tv.set_content(self._stack)

        self._build_dashboard()
        self._build_signal_page("WIFI",      "wifi-symbolic",
                                "network-wireless-symbolic", "WIFI")
        self._build_signal_page("BLUETOOTH", "bluetooth-symbolic",
                                "bluetooth-symbolic", "BLUETOOTH")
        self._build_signal_page("SDR RADIO", "audio-input-microphone-symbolic",
                                "audio-input-microphone-symbolic", "RTL_SDR")
        self._build_peers_page()
        self._build_settings_page()

        bar = Adw.ViewSwitcherBar()
        bar.set_stack(self._stack)
        bar.set_reveal(True)
        tv.add_bottom_bar(bar)

        GLib.timeout_add(2000,  self._tick)
        GLib.timeout_add(15000, self._check_peers_bg)

    # ── Dashboard page ────────────────────────────────────────────────────────

    def _build_dashboard(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._stack.add_titled_with_icon(
            scroll, "dashboard", "Dashboard", "view-dashboard-symbolic"
        )

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_start(14); outer.set_margin_end(14)
        outer.set_margin_top(14);   outer.set_margin_bottom(14)
        scroll.set_child(outer)

        # ── Command panel ─────────────────────────────────────────────────
        cmd = Gtk.Frame(); cmd.add_css_class("panel-green")
        cmd_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        cmd_inner.set_margin_start(14); cmd_inner.set_margin_end(14)
        cmd_inner.set_margin_top(14);   cmd_inner.set_margin_bottom(14)
        cmd.set_child(cmd_inner)
        outer.append(cmd)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        cmd_inner.append(top_row)

        # Radar
        self._radar = RadarWidget()
        top_row.append(self._radar)

        # Stats column
        stats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        stats_box.set_valign(Gtk.Align.CENTER)
        top_row.append(stats_box)

        row, self._cnt_wifi  = _stat_row(C["wifi"],   "WIFI",   "stat-green")
        stats_box.append(row)
        row, self._cnt_bt    = _stat_row(C["bt"],     "BT/BLE", "stat-blue")
        stats_box.append(row)
        row, self._cnt_cell  = _stat_row(C["cell"],   "CELL",   "stat-orange")
        stats_box.append(row)
        row, self._cnt_sdr   = _stat_row(C["sdr"],    "SDR",    "stat-purple")
        stats_box.append(row)
        row, self._cnt_alert = _stat_row(C["red"],    "ALERTS", "stat-red")
        stats_box.append(row)

        # Awareness strip
        awareness = Gtk.Frame(); awareness.add_css_class("panel-dark")
        awareness.set_hexpand(True)
        aw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        aw_box.set_margin_start(12); aw_box.set_margin_end(12)
        aw_box.set_margin_top(10);   aw_box.set_margin_bottom(10)
        awareness.set_child(aw_box)
        top_row.append(awareness)
        top_row.set_hexpand(True); awareness.set_hexpand(True)

        self._aw_title   = _label("AWARENESS TIMELINE", "awareness-title")
        self._aw_summary = _label("No signal profile yet", "awareness-summary")
        self._aw_normal  = _label("Normal: 0",             "awareness-detail")
        self._aw_odd     = _label("One-offs / changes: 0", "awareness-odd")
        self._aw_hint    = _label("Signals synced here appear automatically",
                                  "awareness-hint")
        for w in [self._aw_title, self._aw_summary,
                  self._aw_normal, self._aw_odd, self._aw_hint]:
            aw_box.append(w)

        # ── SDR status badge ──────────────────────────────────────────────
        sdr_badge = Gtk.Frame(); sdr_badge.add_css_class("panel")
        sdr_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        sdr_row.set_margin_start(14); sdr_row.set_margin_end(14)
        sdr_row.set_margin_top(10);   sdr_row.set_margin_bottom(10)
        sdr_badge.set_child(sdr_row)
        outer.append(sdr_badge)

        sdr_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._sdr_status_lbl = _label("RTL-SDR LINK IDLE", "sdr-offline")
        self._sdr_sub_lbl    = _label("USB dongle or remote rtl_tcp feed", "sdr-sub")
        ts_ip = _tailscale_ip()
        port  = self._cfg.get("port", 8765)
        ep    = f"{self._local_ip()}:{port}"
        if ts_ip:
            ep += f"  |  TS {ts_ip}:{port}"
        self._endpoint_lbl = _label(ep, "endpoint-label")
        sdr_info.append(self._sdr_status_lbl)
        sdr_info.append(self._sdr_sub_lbl)
        sdr_info.append(self._endpoint_lbl)
        sdr_row.append(sdr_info)

        # ── Scan button ───────────────────────────────────────────────────
        self._scan_btn = Gtk.Button(label="START SCAN", hexpand=True)
        self._scan_btn.add_css_class("btn-scan-start")
        self._scan_btn.connect("clicked", self._on_scan_toggle)
        outer.append(self._scan_btn)

        # ── Scanner tiles ─────────────────────────────────────────────────
        outer.append(_label("SCANNERS", "section-label"))

        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        outer.append(grid)

        # (count_css, label, sub, page_name_or_None)
        tiles = [
            ("tile-count-green",  "WIFI",      "Linux WLAN scan",        "wifi"),
            ("tile-count-blue",   "BLUETOOTH", "BT/BLE discovery",       "bluetooth"),
            ("tile-count-pink",   "NFC",       "Android only",           None),
            ("tile-count-orange", "CELLULAR",  "Android only",           None),
            ("tile-count-purple", "SDR RADIO", f"{self._local_ip()}:1234", "sdr_radio"),
            ("tile-count-red",    "ALERTS",    "Local app status",       None),
        ]
        self._tile_counts: list[Gtk.Label] = []
        for i, (css, label, sub, page) in enumerate(tiles):
            btn, cnt = _scanner_tile(css, label, sub, navigable=(page is not None))
            if page:
                btn.connect("clicked", lambda _b, p=page: self._stack.set_visible_child_name(p))
            else:
                btn.connect("clicked", lambda _b, lbl=label:
                    self._toast.add_toast(Adw.Toast(title=f"{lbl}: Android-only scanner", timeout=2)))
            grid.attach(btn, i % 2, i // 2, 1, 1)
            self._tile_counts.append(cnt)

        # ── Detected signals (compact) ────────────────────────────────────
        outer.append(_label("DETECTED SIGNALS", "section-label"))
        sw, self._all_store_ref = _make_signal_table()
        sw.set_min_content_height(200)
        sw.set_max_content_height(300)
        outer.append(sw)
        self._all_store = self._all_store_ref

        # ── Log box ───────────────────────────────────────────────────────
        self._log_buf = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self._log_buf, editable=False,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                vexpand=False, monospace=True)
        log_view.add_css_class("log-box")
        log_sw = Gtk.ScrolledWindow()
        log_sw.set_child(log_view)
        log_sw.set_min_content_height(120)
        log_sw.set_max_content_height(160)
        outer.append(log_sw)
        self._log_view = log_view

    # ── Per-scanner signal pages ──────────────────────────────────────────────

    def _build_signal_page(self, title: str, icon: str,
                           fallback_icon: str, filter_type: str) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        try:
            self._stack.add_titled_with_icon(box, title.lower().replace(" ", "_"),
                                             title, icon)
        except Exception:
            self._stack.add_titled_with_icon(box, title.lower().replace(" ", "_"),
                                             title, fallback_icon)

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr.set_margin_start(14); hdr.set_margin_end(14)
        hdr.set_margin_top(10);   hdr.set_margin_bottom(6)
        lbl = _label(title, "section-label")
        lbl.set_hexpand(True)
        self._cnt_scan_label = Gtk.Label(xalign=1)
        self._cnt_scan_label.add_css_class("stat-label")
        hdr.append(lbl)
        box.append(hdr)

        sw, store = _make_signal_table(filter_type)
        sw.set_margin_start(8); sw.set_margin_end(8)
        sw.set_margin_bottom(8)
        box.append(sw)

        # Store reference by filter_type so _refresh_table can update it
        attr = f"_store_{filter_type.lower()}"
        setattr(self, attr, store)

    # ── Peers page ────────────────────────────────────────────────────────────

    def _build_peers_page(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._stack.add_titled_with_icon(
            scroll, "peers", "Peers", "network-workgroup-symbolic"
        )
        clamp = Adw.Clamp(maximum_size=780)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_margin_start(16); outer.set_margin_end(16)
        outer.set_margin_top(16);   outer.set_margin_bottom(16)
        clamp.set_child(outer)
        scroll.set_child(clamp)

        ts_ip   = _tailscale_ip()
        local   = self._local_ip()
        port    = self._cfg.get("port", 8765)

        this_grp = Adw.PreferencesGroup(title="This Node")
        this_grp.add(Adw.ActionRow(title="LAN Address",      subtitle=f"{local}:{port}"))
        self._ts_row = Adw.ActionRow(
            title="Tailscale Address",
            subtitle=f"{ts_ip}:{port}" if ts_ip else "Not connected — run: tailscale up"
        )
        this_grp.add(self._ts_row)
        this_grp.add(Adw.ActionRow(title="Node ID",          subtitle=NODE_ID))
        this_grp.add(Adw.ActionRow(title="Node Name",        subtitle=NODE_NAME))
        outer.append(this_grp)

        # ── Tailscale discovery ───────────────────────────────────────────
        ts_grp_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ts_grp_hdr.append(_label("<b>Tailscale Network</b>", markup=True, css=""))
        ts_grp_hdr.get_first_child().set_hexpand(True)
        scan_ts_btn = Gtk.Button(label="Scan for SnifferOps",
                                 icon_name="network-wireless-symbolic")
        scan_ts_btn.add_css_class("btn-secondary")
        scan_ts_btn.connect("clicked", self._on_scan_tailscale)
        ts_grp_hdr.append(scan_ts_btn)
        outer.append(ts_grp_hdr)

        self._ts_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._ts_list.add_css_class("boxed-list")
        outer.append(self._ts_list)
        self._refresh_ts_list(ts_ip)

        # ── Manual peers ──────────────────────────────────────────────────
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr.append(_label("<b>Manual Peers</b>", markup=True, css=""))
        hdr.get_first_child().set_hexpand(True)
        add_btn = Gtk.Button(label="Add Peer", icon_name="list-add-symbolic")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add_peer)
        hdr.append(add_btn)
        outer.append(hdr)

        self._peer_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._peer_list.add_css_class("boxed-list")
        outer.append(self._peer_list)
        self._rebuild_peers()

        info = Adw.PreferencesGroup(title="Android / Windows Setup")
        info.add(Adw.ActionRow(
            title="LAN — point the other app at this machine",
            subtitle=f"Host: {local}   Port: {port}"
        ))
        if ts_ip:
            info.add(Adw.ActionRow(
                title="Tailscale — works across networks",
                subtitle=f"Host: {ts_ip}   Port: {port}"
            ))
        outer.append(info)

    def _rebuild_peers(self) -> None:
        while self._peer_list.get_first_child():
            self._peer_list.remove(self._peer_list.get_first_child())
        self._peer_status_labels.clear()

        peers = self._cfg.get("peers", [])
        if not peers:
            row = Adw.ActionRow(title="No peers yet",
                                subtitle="Add a Windows or Linux SnifferOps node above")
            row.add_css_class("dim-label")
            self._peer_list.append(row)
            return

        last_syncs = {}
        if _sync_manager:
            last_syncs = dict(_sync_manager._last_sync)

        for i, p in enumerate(peers):
            key = f"{p['host']}:{p.get('port', 8765)}"
            via_tag = "  •  tailscale" if p.get("via") == "tailscale" else ""
            ts = last_syncs.get(key, 0)
            if ts:
                import time as _time
                age = int(_time.time() - ts)
                if age < 60:
                    sync_str = f"  •  synced {age}s ago"
                elif age < 3600:
                    sync_str = f"  •  synced {age // 60}m ago"
                else:
                    sync_str = f"  •  synced {age // 3600}h ago"
            else:
                sync_str = "  •  not synced yet"
            row = Adw.ActionRow(
                title=p.get("name", p["host"]),
                subtitle=f"{p['host']}:{p.get('port', 8765)}{via_tag}{sync_str}"
            )
            # Online dot
            dot = Gtk.Label()
            dot.set_markup(f'<span foreground="{C["muted"]}" size="large">●</span>')
            row.add_suffix(dot)
            self._peer_status_labels.append(dot)
            # Sync-now button
            sync_btn = Gtk.Button(icon_name="view-refresh-symbolic",
                                  valign=Gtk.Align.CENTER, tooltip_text="Sync now")
            sync_btn.add_css_class("flat")
            sync_btn.connect("clicked", self._on_sync_peer_now, p)
            row.add_suffix(sync_btn)
            # Remove button
            rm = Gtk.Button(icon_name="list-remove-symbolic",
                            valign=Gtk.Align.CENTER, tooltip_text="Remove peer")
            rm.add_css_class("flat")
            rm.connect("clicked", self._on_remove_peer, i)
            row.add_suffix(rm)
            self._peer_list.append(row)

    def _refresh_ts_list(self, local_ts_ip: str = "") -> None:
        while self._ts_list.get_first_child():
            self._ts_list.remove(self._ts_list.get_first_child())
        nodes = _tailscale_nodes()
        if not nodes:
            placeholder = Adw.ActionRow(
                title="No Tailscale peers visible",
                subtitle="Authenticate with 'tailscale up' or click Scan"
            )
            self._ts_list.append(placeholder)
            return
        port = self._cfg.get("port", 8765)
        already = {p["host"] for p in self._cfg.get("peers", [])}
        for node in nodes:
            ip   = node["ip"]
            name = node["name"]
            row  = Adw.ActionRow(title=name,
                                 subtitle=f"{ip}:{port}  •  {node['os']}")
            if ip in already:
                lbl = Gtk.Label(label="Added", xalign=1)
                lbl.add_css_class("dim-label")
                row.add_suffix(lbl)
            else:
                add_btn = Gtk.Button(label="Add", valign=Gtk.Align.CENTER,
                                     icon_name="list-add-symbolic")
                add_btn.add_css_class("suggested-action")
                add_btn.connect("clicked", self._on_add_ts_peer, ip, name, port)
                row.add_suffix(add_btn)
            self._ts_list.append(row)

    def _on_scan_tailscale(self, _btn) -> None:
        self.toast("Scanning Tailscale network…")
        def _work():
            ts_ip = _tailscale_ip()
            GLib.idle_add(self._refresh_ts_list, ts_ip)
        threading.Thread(target=_work, daemon=True).start()

    def _on_add_ts_peer(self, _btn, ip: str, name: str, port: int) -> None:
        peer = {"host": ip, "port": port, "name": name, "via": "tailscale"}
        self._cfg.setdefault("peers", []).append(peer)
        save_config(self._cfg)
        if _sync_manager: _sync_manager.add_peer(ip, port, name)
        self._rebuild_peers()
        self._refresh_ts_list()
        self.toast(f"Added Tailscale peer: {name}")

    def _on_add_peer(self, _btn) -> None:
        dlg = Adw.MessageDialog(transient_for=self, heading="Add Peer Node",
                                body="IP address of a Windows or Linux SnifferOps node.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("add",    "Add")
        dlg.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        grp = Adw.PreferencesGroup(); grp.set_margin_top(8)
        host_row = Adw.EntryRow(title="Host / IP address")
        port_row = Adw.EntryRow(title="Port"); port_row.set_text("8765")
        name_row = Adw.EntryRow(title="Nickname (optional)")
        grp.add(host_row); grp.add(port_row); grp.add(name_row)
        dlg.set_extra_child(grp)
        def _resp(d, r):
            if r != "add": return
            host = host_row.get_text().strip()
            if not host: return
            try:    port = int(port_row.get_text().strip() or "8765")
            except: port = 8765
            name = name_row.get_text().strip() or host
            peer = {"host": host, "port": port, "name": name}
            self._cfg.setdefault("peers", []).append(peer)
            save_config(self._cfg)
            if _sync_manager: _sync_manager.add_peer(host, port, name)
            self._rebuild_peers()
            self.toast(f"Added peer: {name}")
        dlg.connect("response", _resp); dlg.present()

    def _on_sync_peer_now(self, _btn, peer: dict) -> None:
        self.toast(f"Syncing {peer.get('name', peer['host'])}…")
        def _work():
            if _sync_manager:
                results = _sync_manager.sync_all_now()
                name = peer.get("name", peer["host"])
                status = results.get(name, "done")
                GLib.idle_add(self.toast, f"{name}: {status}")
                GLib.idle_add(self._rebuild_peers)
        threading.Thread(target=_work, daemon=True).start()

    def _on_remove_peer(self, _btn, idx: int) -> None:
        peers = self._cfg.get("peers", [])
        if 0 <= idx < len(peers):
            removed = peers.pop(idx)
            save_config(self._cfg)
            if _sync_manager: _sync_manager.remove_peer(removed["host"], removed.get("port", 8765))
            self._rebuild_peers()
            self.toast(f"Removed {removed.get('name', removed['host'])}")

    # ── Settings page ─────────────────────────────────────────────────────────

    def _build_settings_page(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._stack.add_titled_with_icon(
            scroll, "settings", "Settings", "preferences-system-symbolic"
        )
        clamp = Adw.Clamp(maximum_size=700)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_start(16); box.set_margin_end(16)
        box.set_margin_top(16);   box.set_margin_bottom(16)
        clamp.set_child(box); scroll.set_child(clamp)

        scan_grp = Adw.PreferencesGroup(title="Scanners")
        self._sw_wifi = Gtk.Switch(valign=Gtk.Align.CENTER,
                                   active=self._cfg.get("wifi", True))
        self._sw_bt   = Gtk.Switch(valign=Gtk.Align.CENTER,
                                   active=self._cfg.get("bluetooth", True))
        self._sw_sdr  = Gtk.Switch(valign=Gtk.Align.CENTER,
                                   active=self._cfg.get("sdr", False))
        for sw, title, sub in [
            (self._sw_wifi, "WiFi Scanner",      "nmcli / iwlist"),
            (self._sw_bt,   "Bluetooth Scanner", "bluetoothctl / hcitool"),
            (self._sw_sdr,  "RTL-SDR Scanner",   "Requires hardware or remote rtl_tcp"),
        ]:
            row = Adw.ActionRow(title=title, subtitle=sub)
            row.add_suffix(sw); row.set_activatable_widget(sw)
            scan_grp.add(row)
        box.append(scan_grp)

        net_grp = Adw.PreferencesGroup(title="Network")
        self._port_entry       = Adw.EntryRow(title="Sync Port")
        self._port_entry.set_text(str(self._cfg.get("port", 8765)))
        self._sdr_remote_entry = Adw.EntryRow(title="Remote rtl_tcp (host:port)")
        self._sdr_remote_entry.set_text(self._cfg.get("sdr_remote", ""))
        net_grp.add(self._port_entry)
        net_grp.add(self._sdr_remote_entry)
        box.append(net_grp)

        save_btn = Gtk.Button(label="Save Settings")
        save_btn.add_css_class("suggested-action")
        save_btn.set_halign(Gtk.Align.END)
        save_btn.connect("clicked", self._save_settings)
        box.append(save_btn)

        data_grp = Adw.PreferencesGroup(title="Data", description=f"Log: {LOG_PATH}")
        clear_btn = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        clear_btn.add_css_class("destructive-action")
        clear_btn.connect("clicked", self._confirm_clear)
        clear_row = Adw.ActionRow(title="Clear Awareness Log",
                                  subtitle="Deletes all detected signals")
        clear_row.add_suffix(clear_btn)
        data_grp.add(clear_row)
        box.append(data_grp)

    def _save_settings(self, _btn) -> None:
        try:    self._cfg["port"] = int(self._port_entry.get_text().strip())
        except: pass
        self._cfg["wifi"]       = self._sw_wifi.get_active()
        self._cfg["bluetooth"]  = self._sw_bt.get_active()
        self._cfg["sdr"]        = self._sw_sdr.get_active()
        self._cfg["sdr_remote"] = self._sdr_remote_entry.get_text().strip()
        save_config(self._cfg)
        self.toast("Settings saved — restart to apply scanner changes")

    def _confirm_clear(self, _btn) -> None:
        dlg = Adw.MessageDialog(transient_for=self, heading="Clear Awareness Log?",
                                body="All detected signals will be permanently deleted.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("clear",  "Clear")
        dlg.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        def _resp(d, r):
            if r == "clear":
                import json
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                with open(LOG_PATH, "w") as f:
                    json.dump({"Schema": 1, "CreatedAt": now,
                               "UpdatedAt": now, "Signals": {}}, f, indent=2)
                self.toast("Awareness log cleared")
        dlg.connect("response", _resp); dlg.present()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _tick(self) -> bool:
        try:
            self._refresh_all()
        except Exception:
            pass
        return GLib.SOURCE_CONTINUE

    def _refresh_all(self) -> None:
        if not awareness_log._log_path:
            return
        rows = awareness_log.get_rows()

        # Counts per type
        type_counts: dict[str, int] = {}
        for r in rows:
            t = r.get("Type", "")
            type_counts[t] = type_counts.get(t, 0) + 1

        wifi_n  = type_counts.get("WIFI", 0)
        bt_n    = type_counts.get("BLUETOOTH", 0) + type_counts.get("BLE", 0)
        cell_n  = type_counts.get("CELLULAR", 0)
        sdr_n   = type_counts.get("RTL_SDR", 0)
        alert_n = _scan_stats.get("alerts", 0)

        # Stat counters
        self._cnt_wifi.set_text(str(wifi_n))
        self._cnt_bt.set_text(str(bt_n))
        self._cnt_cell.set_text(str(cell_n))
        self._cnt_sdr.set_text(str(sdr_n))
        self._cnt_alert.set_text(str(alert_n))

        # Tile counts
        tile_vals = [wifi_n, bt_n, 0, cell_n, sdr_n, alert_n]
        for lbl, val in zip(self._tile_counts, tile_vals):
            lbl.set_text(str(val))

        # Awareness strip
        total = len(rows)
        normal_n = sum(1 for r in rows
                       if (r.get("Confidence") or "").upper() in ("SAFE", "UNKNOWN", ""))
        odd_n = total - normal_n
        self._aw_summary.set_text(f"{total} known / {_scan_stats['syncs']} syncs")
        self._aw_normal.set_text(f"Normal: {normal_n}")
        self._aw_odd.set_text(f"Watch / alerts: {odd_n}")

        # SDR link status
        sdr_on = self._cfg.get("sdr", False)
        if sdr_on:
            self._sdr_status_lbl.set_text("RTL-SDR LINK ONLINE")
            self._sdr_status_lbl.remove_css_class("sdr-offline")
            self._sdr_status_lbl.add_css_class("sdr-online")
        else:
            self._sdr_status_lbl.set_text("RTL-SDR LINK IDLE")
            self._sdr_status_lbl.remove_css_class("sdr-online")
            self._sdr_status_lbl.add_css_class("sdr-offline")

        # Log line
        self._append_log(
            f"[{time.strftime('%H:%M:%S')}] "
            f"WiFi:{_scan_stats['wifi']} BT:{_scan_stats['bt']} "
            f"SDR:{_scan_stats['sdr']} Signals:{total}\n"
        )

        # Populate signal stores
        for store in [self._all_store,
                      getattr(self, "_store_wifi", None),
                      getattr(self, "_store_bluetooth", None),
                      getattr(self, "_store_rtl_sdr", None)]:
            if store is None:
                continue
            store.remove_all()
            for r in rows:
                store.append(SignalRow(r))

    def _append_log(self, text: str) -> None:
        buf = self._log_buf
        end = buf.get_end_iter()
        buf.insert(end, text)
        # Keep last 80 lines
        line_count = buf.get_line_count()
        if line_count > 80:
            start = buf.get_start_iter()
            trim_end = buf.get_iter_at_line(line_count - 80)
            buf.delete(start, trim_end)

    def _check_peers_bg(self) -> bool:
        peers = self._cfg.get("peers", [])
        if not peers:
            return GLib.SOURCE_CONTINUE
        def _work():
            results = [check_peer_health(p["host"], p.get("port", 8765)) for p in peers]
            GLib.idle_add(self._apply_peer_dots, results)
        threading.Thread(target=_work, daemon=True).start()
        return GLib.SOURCE_CONTINUE

    def _apply_peer_dots(self, results: list[bool]) -> bool:
        for dot, online in zip(self._peer_status_labels, results):
            c = C["green"] if online else C["red"]
            dot.set_markup(f'<span foreground="{c}" size="large">●</span>')
        return GLib.SOURCE_REMOVE

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_scan_toggle(self, _btn) -> None:
        global _scan_active
        _scan_active = not _scan_active
        self._radar.set_active(_scan_active)
        if _scan_active:
            self._scan_btn.set_label("STOP SCAN")
            self._scan_btn.remove_css_class("btn-scan-start")
            self._scan_btn.add_css_class("btn-scan-stop")
            self.toast("Scanning started")
        else:
            self._scan_btn.set_label("START SCAN")
            self._scan_btn.remove_css_class("btn-scan-stop")
            self._scan_btn.add_css_class("btn-scan-start")
            self.toast("Scanning paused")

    def _on_refresh(self, _btn) -> None:
        if _sync_manager:
            threading.Thread(target=_sync_manager.sync_all_now, daemon=True).start()
        try:
            from scanners.wifi_scanner import scan_once
            def _do():
                results = scan_once()
                if results:
                    _on_wifi(results)
            threading.Thread(target=_do, daemon=True).start()
        except Exception:
            pass
        self.toast("Refresh triggered")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def toast(self, msg: str) -> None:
        self._toast.add_toast(Adw.Toast(title=msg, timeout=3))

    def _local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]; s.close()
            return ip
        except Exception:
            return "127.0.0.1"


# ── Application ───────────────────────────────────────────────────────────────

class SnifferOpsApp(Adw.Application):

    def __init__(self):
        super().__init__(application_id="com.snifferops.linux",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        # Load CSS
        provider = Gtk.CssProvider()
        provider.load_from_string(_build_css())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

        for name, handler in [("about", self._on_about), ("quit", lambda *_: self.quit())]:
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", handler)
            self.add_action(act)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self) -> None:
        win = self.get_active_window()
        if not win:
            os.makedirs(DATA_DIR, exist_ok=True)
            awareness_log.initialize(LOG_PATH)
            win = SnifferOpsWindow(self)
            self._start_services(win)
        win.present()

    def _start_services(self, win: SnifferOpsWindow) -> None:
        global _sync_manager
        cfg = win._cfg
        awareness_log.start_server("0.0.0.0", cfg.get("port", 8765))

        def _on_peers_discovered(new_peers: list[dict]) -> None:
            """Called from sync thread when Tailscale auto-discovers new nodes."""
            for p in new_peers:
                if p not in cfg.setdefault("peers", []):
                    cfg["peers"].append(p)
            save_config(cfg)
            GLib.idle_add(win._rebuild_peers)
            GLib.idle_add(win.toast,
                f"Auto-connected {len(new_peers)} Tailscale node(s)")

        _sync_manager = NodeSyncManager(
            awareness_log, NODE_ID, NODE_NAME,
            peers=cfg.get("peers", []),
            on_peer_update=_on_peers_discovered,
        )
        _sync_manager.start()

        if cfg.get("wifi", True):
            from scanners.wifi_scanner import WifiScanner
            WifiScanner(_on_wifi).start()

        if cfg.get("bluetooth", True):
            from scanners.bluetooth_scanner import BluetoothScanner
            BluetoothScanner(_on_bt).start()

        if cfg.get("sdr", False):
            remote = cfg.get("sdr_remote", "").strip()
            if remote:
                from scanners.rtl_sdr_scanner import NetworkRtlSdrScanner
                parts = remote.split(":")
                NetworkRtlSdrScanner(parts[0],
                                     int(parts[1]) if len(parts) > 1 else 1234,
                                     _on_sdr).start()
            else:
                from scanners.rtl_sdr_scanner import RtlSdrScanner
                RtlSdrScanner(_on_sdr).start()

        # Immediate WiFi scan on launch
        if cfg.get("wifi", True):
            def _initial():
                try:
                    from scanners.wifi_scanner import scan_once
                    results = scan_once()
                    if results: _on_wifi(results)
                except Exception:
                    pass
            threading.Thread(target=_initial, daemon=True).start()

    def _on_about(self, *_) -> None:
        Adw.AboutWindow(
            transient_for=self.get_active_window(),
            application_name="SnifferOps",
            application_icon="com.snifferops.linux",
            version="1.0.0",
            developer_name="SnifferOps Project",
            comments="Multi-platform RF and wireless signal awareness hub.\n"
                     "Syncs with Android and Windows nodes on the same LAN.",
            website="https://github.com/jessedaustin93/Sniffer-Ops",
            license_type=Gtk.License.MIT_X11,
        ).present()


def main() -> None:
    SnifferOpsApp().run(sys.argv)


if __name__ == "__main__":
    main()
