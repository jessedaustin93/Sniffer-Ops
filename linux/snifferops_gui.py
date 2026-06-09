#!/usr/bin/env python3
"""
SnifferOps Linux — GTK4/Adwaita GUI
Launches without a terminal, installs into the GNOME app menu.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, GObject, Pango

import os
import sys
import platform
import threading
import time
import uuid

# Add the linux/ dir to path when launched from .desktop
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import awareness_log
import signal_classifier
from lenses.all_lenses import route
from sync.node_sync import NodeSyncManager, check_peer_health

DATA_DIR = os.path.expanduser("~/.snifferops")
LOG_PATH = os.path.join(DATA_DIR, "awareness.json")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
SYNC_PORT = 8765
NODE_ID = str(uuid.uuid4())[:16]
NODE_NAME = f"linux-{platform.node()}"

_scan_stats = {"wifi": 0, "bt": 0, "sdr": 0, "syncs": 0, "errors": 0}
_scanner_threads: list = []
_sync_manager: NodeSyncManager | None = None


# ── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> dict:
    import json
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"port": 8765, "bind": "0.0.0.0",
                "wifi": True, "bluetooth": True, "sdr": False,
                "sdr_remote": "", "peers": []}


def save_config(cfg: dict) -> None:
    import json
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Scanner callbacks (run in background threads) ─────────────────────────────

def _submit(signals: list[dict], signal_type: str) -> None:
    snapshot = {
        "schema": 1, "nodeId": NODE_ID, "nodeName": NODE_NAME,
        "capturedAt": int(time.time() * 1000),
        "location": {}, "completeTypes": [signal_type], "signals": signals,
    }
    awareness_log.merge_snapshot(snapshot)
    _scan_stats["syncs"] += 1


def _on_wifi(signals):
    for s in signals:
        ex = signal_classifier.classify_wifi(s)
        s["deviceClass"] = ex.specific_type
    _submit(signals, "WIFI")
    _scan_stats["wifi"] += len(signals)


def _on_bt(devices):
    for d in devices:
        ex = signal_classifier.classify_bluetooth(d)
        d["deviceClass"] = ex.specific_type
    _submit(devices, "BLUETOOTH")
    _scan_stats["bt"] += len(devices)


def _on_sdr(signals):
    for s in signals:
        freq = s.get("frequencyHz") or 0
        ex = signal_classifier.classify_sdr(freq)
        s["deviceClass"] = ex.specific_type
        directive = route(freq)
        if directive:
            s["notes"] = f"Lens: {directive.kind}/{directive.mode or directive.title}"
    _submit(signals, "RTL_SDR")
    _scan_stats["sdr"] += len(signals)


# ── GObject row model ─────────────────────────────────────────────────────────

class SignalRow(GObject.Object):
    __gtype_name__ = "SignalRow"

    sig_type    = GObject.Property(type=str, default="")
    name        = GObject.Property(type=str, default="")
    address     = GObject.Property(type=str, default="")
    strength    = GObject.Property(type=str, default="")
    cls         = GObject.Property(type=str, default="")
    threat      = GObject.Property(type=str, default="")
    details     = GObject.Property(type=str, default="")

    def __init__(self, row: dict):
        super().__init__()
        self.sig_type = str(row.get("Type") or "")
        self.name     = str(row.get("Signal") or "")
        self.address  = str(row.get("AddressOrFrequency") or "")
        self.strength = str(row.get("StrengthOrPower") or "")
        self.cls      = str(row.get("Classification") or "")
        self.threat   = str(row.get("Confidence") or "")
        self.details  = str(row.get("Details") or "")


# ── Peer row model ────────────────────────────────────────────────────────────

class PeerRow(GObject.Object):
    __gtype_name__ = "PeerRow"
    host    = GObject.Property(type=str, default="")
    port    = GObject.Property(type=int, default=8765)
    name    = GObject.Property(type=str, default="")
    online  = GObject.Property(type=bool, default=False)

    def __init__(self, d: dict, online: bool = False):
        super().__init__()
        self.host   = d.get("host", "")
        self.port   = d.get("port", 8765)
        self.name   = d.get("name", self.host)
        self.online = online


# ── Main window ───────────────────────────────────────────────────────────────

class SnifferOpsWindow(Adw.ApplicationWindow):

    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("SnifferOps")
        self.set_default_size(1280, 760)

        self._cfg = load_config()
        self._signal_store = Gio.ListStore(item_type=SignalRow)
        self._peer_store   = Gio.ListStore(item_type=PeerRow)

        # Top-level layout
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # Header bar
        header = Adw.HeaderBar()
        header.set_centering_policy(Adw.CenteringPolicy.STRICT)
        toolbar_view.add_top_bar(header)

        # Title with switcher
        self._switcher = Adw.ViewSwitcher()
        self._switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self._switcher)

        # Refresh button
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Force sync now")
        refresh_btn.connect("clicked", self._on_force_sync)
        header.pack_end(refresh_btn)

        # Menu button
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("About SnifferOps", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        # View stack
        self._stack = Adw.ViewStack()
        self._switcher.set_stack(self._stack)
        toolbar_view.set_content(self._stack)

        self._build_awareness_page()
        self._build_peers_page()
        self._build_settings_page()

        # Status bar
        self._status_label = Gtk.Label(xalign=0)
        self._status_label.add_css_class("caption")
        self._status_label.set_margin_start(12)
        self._status_label.set_margin_end(12)
        self._status_label.set_margin_top(4)
        self._status_label.set_margin_bottom(4)
        toolbar_view.add_bottom_bar(self._status_label)

        # Refresh timer
        GLib.timeout_add(2000, self._refresh)
        self._refresh()

    # ── Awareness page ──────────────────────────────────────────────────────

    def _build_awareness_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._stack.add_titled_with_icon(page, "awareness", "Awareness Map",
                                         "network-wireless-symbolic")

        # Search bar
        search_bar = Gtk.SearchEntry()
        search_bar.set_placeholder_text("Filter signals…")
        search_bar.set_margin_start(12)
        search_bar.set_margin_end(12)
        search_bar.set_margin_top(8)
        search_bar.set_margin_bottom(4)
        search_bar.connect("search-changed", self._on_search_changed)
        page.append(search_bar)
        self._search_bar = search_bar

        # Filter model
        self._filter = Gtk.StringFilter(expression=None)
        self._filter_model = Gtk.FilterListModel(model=self._signal_store)
        self._sorted_model = Gtk.SortListModel(model=self._filter_model)

        # ColumnView
        self._column_view = Gtk.ColumnView(
            model=Gtk.NoSelection(model=self._sorted_model),
            show_row_separators=True,
            show_column_separators=True,
        )
        self._column_view.add_css_class("data-table")

        sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        sw.set_child(self._column_view)
        sw.set_margin_start(8)
        sw.set_margin_end(8)
        sw.set_margin_bottom(8)
        page.append(sw)

        self._add_column("Type",        "sig_type",  120,  False)
        self._add_column("Signal",      "name",      220,  True)
        self._add_column("Addr / Freq", "address",   180,  False)
        self._add_column("Strength",    "strength",   80,  False)
        self._add_column("Class",       "cls",       220,  True)
        self._add_column("Threat",      "threat",     80,  False)
        self._add_column("Details",     "details",   320,  True)

    def _add_column(self, title: str, prop: str, width: int, expand: bool):
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda f, item: self._col_setup(item))
        factory.connect("bind", lambda f, item, p=prop: self._col_bind(item, p))
        col = Gtk.ColumnViewColumn(title=title, factory=factory)
        col.set_fixed_width(width)
        col.set_expand(expand)
        self._column_view.append_column(col)

    def _col_setup(self, item):
        lbl = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        lbl.set_margin_start(6)
        lbl.set_margin_end(6)
        lbl.set_margin_top(4)
        lbl.set_margin_bottom(4)
        item.set_child(lbl)

    def _col_bind(self, item, prop: str):
        row: SignalRow = item.get_item()
        lbl: Gtk.Label = item.get_child()
        val = row.get_property(prop)

        # Colour-code threat column
        if prop == "threat":
            colours = {"ALERT": "red", "SUSPICIOUS": "orange",
                       "SAFE": "green", "UNKNOWN": ""}
            lbl.set_markup(f'<span foreground="{colours.get(val, "")}">{GLib.markup_escape_text(val)}</span>'
                           if val in colours and colours[val]
                           else GLib.markup_escape_text(val))
        elif prop == "sig_type":
            icons = {"WIFI": "📶", "BLUETOOTH": "🔵", "RTL_SDR": "📡",
                     "CELLULAR": "📱", "NFC": "🔖", "BLE": "🔵"}
            icon = icons.get(val, "")
            lbl.set_text(f"{icon} {val}" if icon else val)
        else:
            lbl.set_text(val)

    def _on_search_changed(self, entry):
        txt = entry.get_text().strip().lower()
        if not txt:
            self._filter_model.set_filter(None)
        else:
            expr = Gtk.PropertyExpression.new(SignalRow, None, "name")
            sf = Gtk.StringFilter(expression=expr)
            sf.set_search(txt)
            sf.set_ignore_case(True)
            sf.set_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
            self._filter_model.set_filter(sf)

    # ── Peers page ──────────────────────────────────────────────────────────

    def _build_peers_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._stack.add_titled_with_icon(box, "peers", "Peers",
                                         "network-workgroup-symbolic")

        clamp = Adw.Clamp(maximum_size=800)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inner.set_margin_start(16)
        inner.set_margin_end(16)
        inner.set_margin_top(16)
        inner.set_margin_bottom(16)
        clamp.set_child(inner)
        box.append(clamp)

        # Header row
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = Gtk.Label(label="<b>Sync Peers</b>", use_markup=True, xalign=0, hexpand=True)
        add_btn = Gtk.Button(label="Add Peer", icon_name="list-add-symbolic")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add_peer)
        hbox.append(lbl)
        hbox.append(add_btn)
        inner.append(hbox)

        sub = Gtk.Label(label="Add Windows or Linux nodes. Android connects to this machine directly.",
                        xalign=0, wrap=True)
        sub.add_css_class("dim-label")
        inner.append(sub)

        # Peer list
        self._peer_list_box = Gtk.ListBox()
        self._peer_list_box.add_css_class("boxed-list")
        self._peer_list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        inner.append(self._peer_list_box)

        self._rebuild_peer_list()

        # Info card
        card = Adw.PreferencesGroup()
        card.set_title("This Node")
        card.set_description("Android and other nodes connect to this address")

        ip_row = Adw.ActionRow(title="IP Address", subtitle=self._get_local_ip())
        port_row = Adw.ActionRow(title="Sync Port", subtitle=str(self._cfg.get("port", 8765)))
        node_row = Adw.ActionRow(title="Node ID", subtitle=NODE_ID)
        card.add(ip_row)
        card.add(port_row)
        card.add(node_row)
        inner.append(card)

    def _rebuild_peer_list(self):
        # Clear
        while True:
            child = self._peer_list_box.get_first_child()
            if child is None:
                break
            self._peer_list_box.remove(child)

        peers = self._cfg.get("peers", [])
        if not peers:
            row = Adw.ActionRow(title="No peers configured",
                                subtitle="Add a Windows or Linux node above")
            row.add_css_class("dim-label")
            self._peer_list_box.append(row)
            return

        for i, p in enumerate(peers):
            row = Adw.ActionRow(
                title=p.get("name", p["host"]),
                subtitle=f"{p['host']}:{p.get('port', 8765)}",
            )
            # Status indicator
            status = Gtk.Label()
            status.set_markup('<span foreground="gray">●</span>')
            status.set_name(f"peer-status-{i}")
            row.add_suffix(status)

            # Remove button
            rm = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER)
            rm.add_css_class("flat")
            rm.add_css_class("destructive-action")
            rm.connect("clicked", self._on_remove_peer, i)
            row.add_suffix(rm)

            self._peer_list_box.append(row)

    def _on_add_peer(self, _btn):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Add Peer Node",
            body="Enter the IP address of a Windows or Linux SnifferOps node.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(8)

        host_row = Adw.EntryRow(title="Host / IP address")
        port_row = Adw.EntryRow(title="Port")
        port_row.set_text("8765")
        name_row = Adw.EntryRow(title="Nickname (optional)")
        pref = Adw.PreferencesGroup()
        pref.add(host_row)
        pref.add(port_row)
        pref.add(name_row)
        content.append(pref)
        dialog.set_extra_child(content)

        def on_response(d, resp):
            if resp == "add":
                host = host_row.get_text().strip()
                if not host:
                    return
                try:
                    port = int(port_row.get_text().strip() or "8765")
                except ValueError:
                    port = 8765
                name = name_row.get_text().strip() or host
                peer = {"host": host, "port": port, "name": name}
                self._cfg.setdefault("peers", []).append(peer)
                save_config(self._cfg)
                if _sync_manager:
                    _sync_manager.add_peer(host, port, name)
                self._rebuild_peer_list()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_remove_peer(self, _btn, idx: int):
        peers = self._cfg.get("peers", [])
        if 0 <= idx < len(peers):
            removed = peers.pop(idx)
            save_config(self._cfg)
            if _sync_manager:
                _sync_manager.remove_peer(removed["host"], removed.get("port", 8765))
            self._rebuild_peer_list()

    # ── Settings page ───────────────────────────────────────────────────────

    def _build_settings_page(self):
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._stack.add_titled_with_icon(scroll, "settings", "Settings",
                                         "preferences-system-symbolic")

        clamp = Adw.Clamp(maximum_size=700)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        clamp.set_child(box)
        scroll.set_child(clamp)

        # Scanners group
        scan_grp = Adw.PreferencesGroup(title="Scanners",
                                         description="Enable/disable signal scanning modules")

        self._sw_wifi = Gtk.Switch(valign=Gtk.Align.CENTER,
                                   active=self._cfg.get("wifi", True))
        wifi_row = Adw.ActionRow(title="WiFi Scanner",
                                 subtitle="Scans for nearby WiFi networks via nmcli")
        wifi_row.add_suffix(self._sw_wifi)
        wifi_row.set_activatable_widget(self._sw_wifi)

        self._sw_bt = Gtk.Switch(valign=Gtk.Align.CENTER,
                                 active=self._cfg.get("bluetooth", True))
        bt_row = Adw.ActionRow(title="Bluetooth Scanner",
                               subtitle="Scans for BT/BLE devices via bluetoothctl")
        bt_row.add_suffix(self._sw_bt)
        bt_row.set_activatable_widget(self._sw_bt)

        self._sw_sdr = Gtk.Switch(valign=Gtk.Align.CENTER,
                                  active=self._cfg.get("sdr", False))
        sdr_row = Adw.ActionRow(title="RTL-SDR Scanner",
                                subtitle="Requires rtl-sdr hardware or a remote rtl_tcp server")
        sdr_row.add_suffix(self._sw_sdr)
        sdr_row.set_activatable_widget(self._sw_sdr)

        scan_grp.add(wifi_row)
        scan_grp.add(bt_row)
        scan_grp.add(sdr_row)
        box.append(scan_grp)

        # Network group
        net_grp = Adw.PreferencesGroup(title="Network",
                                        description="HTTP sync server (Android connects here)")

        port_entry = Adw.EntryRow(title="Sync Port")
        port_entry.set_text(str(self._cfg.get("port", 8765)))

        sdr_remote_entry = Adw.EntryRow(title="Remote rtl_tcp host:port")
        sdr_remote_entry.set_text(self._cfg.get("sdr_remote", ""))
        sdr_remote_entry.set_show_apply_button(True)

        net_grp.add(port_entry)
        net_grp.add(sdr_remote_entry)
        box.append(net_grp)

        # Save button
        save_btn = Gtk.Button(label="Save & Restart Scanners")
        save_btn.add_css_class("suggested-action")
        save_btn.set_halign(Gtk.Align.END)
        save_btn.connect("clicked", lambda _: self._save_settings(
            port_entry, sdr_remote_entry))
        box.append(save_btn)

        # Data group
        data_grp = Adw.PreferencesGroup(title="Data",
                                         description=f"Awareness log: {LOG_PATH}")
        clear_row = Adw.ActionRow(title="Clear Awareness Log",
                                  subtitle="Removes all detected signals from the database")
        clear_btn = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        clear_btn.add_css_class("destructive-action")
        clear_btn.connect("clicked", self._on_clear_log)
        clear_row.add_suffix(clear_btn)
        data_grp.add(clear_row)
        box.append(data_grp)

    def _save_settings(self, port_entry, sdr_entry):
        try:
            self._cfg["port"] = int(port_entry.get_text().strip())
        except ValueError:
            pass
        self._cfg["wifi"] = self._sw_wifi.get_active()
        self._cfg["bluetooth"] = self._sw_bt.get_active()
        self._cfg["sdr"] = self._sw_sdr.get_active()
        self._cfg["sdr_remote"] = sdr_entry.get_text().strip()
        save_config(self._cfg)
        self._show_toast("Settings saved. Restart the app to apply scanner changes.")

    def _on_clear_log(self, _btn):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Clear Awareness Log?",
            body="All detected signals will be permanently deleted.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        def on_resp(d, resp):
            if resp == "clear":
                import json
                with open(LOG_PATH, "w") as f:
                    from datetime import datetime, timezone
                    f.write(json.dumps({"Schema": 1,
                                        "CreatedAt": datetime.now(timezone.utc).isoformat(),
                                        "UpdatedAt": datetime.now(timezone.utc).isoformat(),
                                        "Signals": {}}, indent=2))
                self._show_toast("Awareness log cleared.")
        dialog.connect("response", on_resp)
        dialog.present()

    # ── Refresh ─────────────────────────────────────────────────────────────

    def _refresh(self) -> bool:
        self._refresh_table()
        self._refresh_status()
        self._refresh_peer_status()
        return GLib.SOURCE_CONTINUE

    def _refresh_table(self):
        rows = awareness_log.get_rows()
        self._signal_store.remove_all()
        for r in rows:
            self._signal_store.append(SignalRow(r))

    def _refresh_status(self):
        total = self._signal_store.get_n_items()
        self._status_label.set_text(
            f"Node: {NODE_NAME}  |  Port: {self._cfg.get('port', 8765)}  |  "
            f"Signals: {total}  |  "
            f"WiFi scans: {_scan_stats['wifi']}  "
            f"BT scans: {_scan_stats['bt']}  "
            f"SDR peaks: {_scan_stats['sdr']}  "
            f"Syncs: {_scan_stats['syncs']}"
        )

    def _refresh_peer_status(self):
        peers = self._cfg.get("peers", [])
        child = self._peer_list_box.get_first_child()
        i = 0
        while child and i < len(peers):
            if isinstance(child, Adw.ActionRow):
                p = peers[i]
                online = check_peer_health(p["host"], p.get("port", 8765))
                # find the status label by iterating suffixes
                suffix = child.get_last_child()
                while suffix:
                    if isinstance(suffix, Gtk.Label) and suffix.get_name().startswith("peer-status"):
                        colour = "green" if online else "red"
                        suffix.set_markup(f'<span foreground="{colour}">●</span>')
                        break
                    suffix = suffix.get_prev_sibling()
                i += 1
            child = child.get_next_sibling()

    def _on_force_sync(self, _btn):
        if _sync_manager:
            threading.Thread(target=_sync_manager.sync_all_now, daemon=True).start()
        self._show_toast("Sync triggered")

    def _show_toast(self, msg: str):
        overlay = Adw.ToastOverlay()
        toast = Adw.Toast(title=msg, timeout=3)
        # Find or create overlay — simple fallback: just print
        try:
            self.get_content().present_toast(toast)
        except Exception:
            pass

    def _get_local_ip(self) -> str:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "unavailable"


# ── Application ───────────────────────────────────────────────────────────────

class SnifferOpsApp(Adw.Application):

    def __init__(self):
        super().__init__(application_id="com.snifferops.linux",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        win = self.get_active_window()
        if not win:
            win = SnifferOpsWindow(self)
            self._start_services(win)
            # Wrap content in ToastOverlay for notifications
            overlay = Adw.ToastOverlay()
            overlay.set_child(win.get_content())
            win.set_content(overlay)
            win._toast_overlay = overlay
            win._show_toast = lambda msg, o=overlay: o.add_toast(Adw.Toast(title=msg, timeout=3))
        win.present()

    def do_startup(self):
        Adw.Application.do_startup(self)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

    def _start_services(self, win):
        global _sync_manager
        cfg = win._cfg
        os.makedirs(DATA_DIR, exist_ok=True)
        awareness_log.initialize(LOG_PATH)
        awareness_log.start_server("0.0.0.0", cfg.get("port", 8765))

        _sync_manager = NodeSyncManager(
            awareness_log, NODE_ID, NODE_NAME,
            peers=cfg.get("peers", [])
        )
        _sync_manager.start()

        if cfg.get("wifi", True):
            from scanners.wifi_scanner import WifiScanner
            WifiScanner(_on_wifi).start()

        if cfg.get("bluetooth", True):
            from scanners.bluetooth_scanner import BluetoothScanner
            BluetoothScanner(_on_bt).start()

        if cfg.get("sdr", False):
            sdr_remote = cfg.get("sdr_remote", "").strip()
            if sdr_remote:
                from scanners.rtl_sdr_scanner import NetworkRtlSdrScanner
                parts = sdr_remote.split(":")
                NetworkRtlSdrScanner(parts[0], int(parts[1]) if len(parts) > 1 else 1234,
                                     _on_sdr).start()
            else:
                from scanners.rtl_sdr_scanner import RtlSdrScanner
                RtlSdrScanner(_on_sdr).start()

    def _on_about(self, *_):
        about = Adw.AboutWindow(
            transient_for=self.get_active_window(),
            application_name="SnifferOps",
            application_icon="com.snifferops.linux",
            version="1.0.0",
            developer_name="SnifferOps Project",
            comments="Multi-platform RF & wireless signal awareness hub.\n"
                     "Syncs with Android and Windows nodes.",
            website="https://github.com/jessedaustin93/Sniffer-Ops",
            license_type=Gtk.License.MIT_X11,
        )
        about.present()


def main():
    app = SnifferOpsApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
