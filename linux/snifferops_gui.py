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
import platform
import socket
import sys
import threading
import time
import uuid

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

_scan_stats: dict = {"wifi": 0, "bt": 0, "sdr": 0, "syncs": 0}
_sync_manager: NodeSyncManager | None = None


# ── Config ────────────────────────────────────────────────────────────────────

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
        ex = signal_classifier.classify_wifi(s)
        s["deviceClass"] = ex.specific_type
    _submit(signals, "WIFI")
    _scan_stats["wifi"] += len(signals)


def _on_bt(devices: list[dict]) -> None:
    for d in devices:
        ex = signal_classifier.classify_bluetooth(d)
        d["deviceClass"] = ex.specific_type
    _submit(devices, "BLUETOOTH")
    _scan_stats["bt"] += len(devices)


def _on_sdr(signals: list[dict]) -> None:
    for s in signals:
        freq = s.get("frequencyHz") or 0
        ex = signal_classifier.classify_sdr(freq)
        s["deviceClass"] = ex.specific_type
        d = route(freq)
        if d:
            s["notes"] = f"Lens: {d.kind}/{d.mode or d.title}"
    _submit(signals, "RTL_SDR")
    _scan_stats["sdr"] += len(signals)


# ── GObject row for ColumnView ────────────────────────────────────────────────

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


# ── Main window ───────────────────────────────────────────────────────────────

class SnifferOpsWindow(Adw.ApplicationWindow):

    def __init__(self, app: "SnifferOpsApp"):
        super().__init__(application=app)
        self.set_title("SnifferOps")
        self.set_default_size(1280, 800)

        self._cfg = load_config()
        self._signal_store = Gio.ListStore(item_type=SignalRow)
        self._peer_status_labels: list[Gtk.Label] = []

        # ── Outer layout: ToastOverlay → ToolbarView ──────────────────────
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self._toast_overlay.set_child(toolbar_view)

        # ── Header bar ────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        title_lbl = Adw.WindowTitle(title="SnifferOps", subtitle=f"Node: {NODE_NAME}")
        header.set_title_widget(title_lbl)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic",
                                 tooltip_text="Force sync with all peers now")
        refresh_btn.connect("clicked", self._on_force_sync)
        header.pack_end(refresh_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("About SnifferOps", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        # ── View stack (3 pages) ──────────────────────────────────────────
        self._stack = Adw.ViewStack()
        toolbar_view.set_content(self._stack)

        self._build_awareness_page()
        self._build_peers_page()
        self._build_settings_page()

        # ── Tab bar at bottom (ViewSwitcherBar — reliable on all widths) ──
        switcher_bar = Adw.ViewSwitcherBar()
        switcher_bar.set_stack(self._stack)
        switcher_bar.set_reveal(True)
        toolbar_view.add_bottom_bar(switcher_bar)

        # ── Status bar ────────────────────────────────────────────────────
        self._status = Gtk.Label(xalign=0)
        self._status.add_css_class("caption")
        self._status.add_css_class("dim-label")
        self._status.set_margin_start(12)
        self._status.set_margin_end(12)
        self._status.set_margin_top(3)
        self._status.set_margin_bottom(3)
        toolbar_view.add_bottom_bar(self._status)

        # ── Refresh loop (2 s table, 15 s peer health check) ─────────────
        self._peer_online: list[bool] = []
        GLib.timeout_add(2000, self._tick)
        GLib.timeout_add(15000, self._check_peers_bg)

    # ── Awareness Map page ────────────────────────────────────────────────────

    def _build_awareness_page(self) -> None:
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._stack.add_titled_with_icon(
            page_box, "awareness", "Awareness Map", "network-wireless-symbolic"
        )

        # Search bar
        search = Gtk.SearchEntry(placeholder_text="Filter by name…")
        search.set_margin_start(12)
        search.set_margin_end(12)
        search.set_margin_top(8)
        search.set_margin_bottom(4)
        search.connect("search-changed", self._on_search)
        page_box.append(search)

        # Filter + sort models
        self._filter_model = Gtk.FilterListModel(model=self._signal_store)
        sorted_model = Gtk.SortListModel(model=self._filter_model)

        # ColumnView
        cv = Gtk.ColumnView(
            model=Gtk.NoSelection(model=sorted_model),
            show_row_separators=True,
            show_column_separators=False,
            vexpand=True,
            hexpand=True,
        )
        cv.add_css_class("data-table")
        self._cv = cv

        sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        sw.set_child(cv)
        sw.set_margin_start(8)
        sw.set_margin_end(8)
        sw.set_margin_bottom(4)
        page_box.append(sw)

        self._add_col(cv, "Type",       "sig_type",  110, False)
        self._add_col(cv, "Signal",     "name",      220, True)
        self._add_col(cv, "Addr / Freq","address",   180, False)
        self._add_col(cv, "dBm",        "strength",   60, False)
        self._add_col(cv, "Class",      "cls",        220, True)
        self._add_col(cv, "Threat",     "threat",      80, False)
        self._add_col(cv, "Details",    "details",    300, True)

    def _add_col(self, cv: Gtk.ColumnView, title: str, prop: str,
                 width: int, expand: bool) -> None:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup",  self._col_setup)
        factory.connect("bind",   lambda f, item, p=prop: self._col_bind(item, p))
        col = Gtk.ColumnViewColumn(title=title, factory=factory,
                                   fixed_width=width, expand=expand)
        cv.append_column(col)

    def _col_setup(self, _factory, item: Gtk.ListItem) -> None:
        lbl = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        lbl.set_margin_start(6)
        lbl.set_margin_end(6)
        lbl.set_margin_top(4)
        lbl.set_margin_bottom(4)
        item.set_child(lbl)

    def _col_bind(self, item: Gtk.ListItem, prop: str) -> None:
        row: SignalRow = item.get_item()
        lbl: Gtk.Label = item.get_child()
        val = row.get_property(prop)

        if prop == "threat":
            colours = {"ALERT": "#ff4444", "SUSPICIOUS": "#ffaa00",
                       "SAFE": "#44ff88"}
            c = colours.get(val.upper(), "")
            lbl.set_markup(
                f'<span foreground="{c}">{GLib.markup_escape_text(val)}</span>'
                if c else GLib.markup_escape_text(val)
            )
        elif prop == "sig_type":
            icons = {"WIFI": "📶 ", "BLUETOOTH": "🔵 ", "BLE": "🔵 ",
                     "RTL_SDR": "📡 ", "CELLULAR": "📱 ", "NFC": "🔖 "}
            lbl.set_text(icons.get(val, "") + val)
        else:
            lbl.set_text(val)

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        txt = entry.get_text().strip()
        if not txt:
            self._filter_model.set_filter(None)
            return
        expr = Gtk.PropertyExpression.new(SignalRow, None, "name")
        sf = Gtk.StringFilter(expression=expr)
        sf.set_search(txt)
        sf.set_ignore_case(True)
        sf.set_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
        self._filter_model.set_filter(sf)

    # ── Peers page ────────────────────────────────────────────────────────────

    def _build_peers_page(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._stack.add_titled_with_icon(
            scroll, "peers", "Peers", "network-workgroup-symbolic"
        )

        clamp = Adw.Clamp(maximum_size=780)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_margin_start(16)
        outer.set_margin_end(16)
        outer.set_margin_top(16)
        outer.set_margin_bottom(16)
        clamp.set_child(outer)
        scroll.set_child(clamp)

        # ── This node info ────────────────────────────────────────────────
        this_grp = Adw.PreferencesGroup(title="This Node",
                                         description="Android and other nodes sync to this address")
        this_grp.add(Adw.ActionRow(title="IP Address",  subtitle=self._local_ip()))
        this_grp.add(Adw.ActionRow(title="Sync Port",   subtitle=str(self._cfg.get("port", 8765))))
        this_grp.add(Adw.ActionRow(title="Node ID",     subtitle=NODE_ID))
        this_grp.add(Adw.ActionRow(title="Node Name",   subtitle=NODE_NAME))
        outer.append(this_grp)

        # ── Peer list ─────────────────────────────────────────────────────
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr_lbl = Gtk.Label(label="<b>Sync Peers</b>", use_markup=True,
                            xalign=0, hexpand=True)
        add_btn = Gtk.Button(label="Add Peer", icon_name="list-add-symbolic")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add_peer)
        hdr.append(hdr_lbl)
        hdr.append(add_btn)
        outer.append(hdr)

        self._peer_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._peer_list.add_css_class("boxed-list")
        outer.append(self._peer_list)
        self._rebuild_peers()

        # ── Android instructions ──────────────────────────────────────────
        info_grp = Adw.PreferencesGroup(title="Android Setup")
        info_grp.add(Adw.ActionRow(
            title="Point the Android app at this machine",
            subtitle=f"Host: {self._local_ip()}   Port: {self._cfg.get('port', 8765)}"
        ))
        outer.append(info_grp)

    def _rebuild_peers(self) -> None:
        while self._peer_list.get_first_child():
            self._peer_list.remove(self._peer_list.get_first_child())
        self._peer_status_labels.clear()

        peers = self._cfg.get("peers", [])
        if not peers:
            placeholder = Adw.ActionRow(
                title="No peers configured yet",
                subtitle="Add a Windows or Linux node above to start cross-node sync"
            )
            placeholder.add_css_class("dim-label")
            self._peer_list.append(placeholder)
            return

        for i, p in enumerate(peers):
            row = Adw.ActionRow(
                title=p.get("name", p["host"]),
                subtitle=f"{p['host']}:{p.get('port', 8765)}"
            )
            dot = Gtk.Label()
            dot.set_markup('<span foreground="#888888" size="large">●</span>')
            row.add_suffix(dot)
            self._peer_status_labels.append(dot)

            rm = Gtk.Button(icon_name="list-remove-symbolic",
                            valign=Gtk.Align.CENTER, tooltip_text="Remove peer")
            rm.add_css_class("flat")
            rm.connect("clicked", self._on_remove_peer, i)
            row.add_suffix(rm)
            self._peer_list.append(row)

    def _on_add_peer(self, _btn) -> None:
        dlg = Adw.MessageDialog(transient_for=self,
                                heading="Add Peer Node",
                                body="Enter the IP address of a Windows or Linux SnifferOps node.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("add",    "Add")
        dlg.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        grp = Adw.PreferencesGroup()
        grp.set_margin_top(8)
        host_row = Adw.EntryRow(title="Host / IP address")
        port_row = Adw.EntryRow(title="Port")
        port_row.set_text("8765")
        name_row = Adw.EntryRow(title="Nickname (optional)")
        grp.add(host_row)
        grp.add(port_row)
        grp.add(name_row)
        dlg.set_extra_child(grp)

        def _resp(d, resp):
            if resp != "add":
                return
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
            self._rebuild_peers()
            self.toast(f"Added peer: {name}")

        dlg.connect("response", _resp)
        dlg.present()

    def _on_remove_peer(self, _btn, idx: int) -> None:
        peers = self._cfg.get("peers", [])
        if 0 <= idx < len(peers):
            removed = peers.pop(idx)
            save_config(self._cfg)
            if _sync_manager:
                _sync_manager.remove_peer(removed["host"], removed.get("port", 8765))
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
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        clamp.set_child(box)
        scroll.set_child(clamp)

        # Scanners
        scan_grp = Adw.PreferencesGroup(
            title="Scanners",
            description="Changes take effect after saving and restarting"
        )

        self._sw_wifi = self._make_switch(self._cfg.get("wifi", True))
        wifi_row = Adw.ActionRow(title="WiFi Scanner",
                                 subtitle="Scans for nearby WiFi networks via nmcli")
        wifi_row.add_suffix(self._sw_wifi)
        wifi_row.set_activatable_widget(self._sw_wifi)

        self._sw_bt = self._make_switch(self._cfg.get("bluetooth", True))
        bt_row = Adw.ActionRow(title="Bluetooth Scanner",
                               subtitle="Discovers BT/BLE devices via bluetoothctl")
        bt_row.add_suffix(self._sw_bt)
        bt_row.set_activatable_widget(self._sw_bt)

        self._sw_sdr = self._make_switch(self._cfg.get("sdr", False))
        sdr_row = Adw.ActionRow(title="RTL-SDR Scanner",
                                subtitle="Requires rtl-sdr hardware or remote rtl_tcp server")
        sdr_row.add_suffix(self._sw_sdr)
        sdr_row.set_activatable_widget(self._sw_sdr)

        scan_grp.add(wifi_row)
        scan_grp.add(bt_row)
        scan_grp.add(sdr_row)
        box.append(scan_grp)

        # Network
        net_grp = Adw.PreferencesGroup(title="Network",
                                        description="HTTP sync server settings")
        self._port_entry = Adw.EntryRow(title="Sync Port")
        self._port_entry.set_text(str(self._cfg.get("port", 8765)))
        self._sdr_remote_entry = Adw.EntryRow(title="Remote rtl_tcp  (host:port)")
        self._sdr_remote_entry.set_text(self._cfg.get("sdr_remote", ""))
        net_grp.add(self._port_entry)
        net_grp.add(self._sdr_remote_entry)
        box.append(net_grp)

        save_btn = Gtk.Button(label="Save Settings")
        save_btn.add_css_class("suggested-action")
        save_btn.set_halign(Gtk.Align.END)
        save_btn.connect("clicked", self._save_settings)
        box.append(save_btn)

        # Data management
        data_grp = Adw.PreferencesGroup(title="Data",
                                         description=f"Log: {LOG_PATH}")
        clear_btn = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        clear_btn.add_css_class("destructive-action")
        clear_btn.connect("clicked", self._confirm_clear)
        clear_row = Adw.ActionRow(title="Clear Awareness Log",
                                  subtitle="Permanently deletes all detected signals")
        clear_row.add_suffix(clear_btn)
        data_grp.add(clear_row)
        box.append(data_grp)

    def _make_switch(self, active: bool) -> Gtk.Switch:
        sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=active)
        return sw

    def _save_settings(self, _btn) -> None:
        try:
            self._cfg["port"] = int(self._port_entry.get_text().strip())
        except ValueError:
            pass
        self._cfg["wifi"]       = self._sw_wifi.get_active()
        self._cfg["bluetooth"]  = self._sw_bt.get_active()
        self._cfg["sdr"]        = self._sw_sdr.get_active()
        self._cfg["sdr_remote"] = self._sdr_remote_entry.get_text().strip()
        save_config(self._cfg)
        self.toast("Settings saved — restart to apply scanner changes")

    def _confirm_clear(self, _btn) -> None:
        dlg = Adw.MessageDialog(transient_for=self,
                                heading="Clear Awareness Log?",
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

        dlg.connect("response", _resp)
        dlg.present()

    # ── Refresh tick ──────────────────────────────────────────────────────────

    def _tick(self) -> bool:
        try:
            self._refresh_table()
        except Exception:
            pass
        self._refresh_status()
        self._apply_peer_dots()
        return GLib.SOURCE_CONTINUE

    def _refresh_table(self) -> None:
        if not awareness_log._log_path:
            return
        rows = awareness_log.get_rows()
        self._signal_store.remove_all()
        for r in rows:
            self._signal_store.append(SignalRow(r))

    def _refresh_status(self) -> None:
        n = self._signal_store.get_n_items()
        self._status.set_text(
            f"Signals: {n}  ·  WiFi scans: {_scan_stats['wifi']}  "
            f"BT scans: {_scan_stats['bt']}  SDR: {_scan_stats['sdr']}  "
            f"Syncs: {_scan_stats['syncs']}"
        )

    def _check_peers_bg(self) -> bool:
        """Run peer health checks in a background thread — never blocks the UI."""
        peers = self._cfg.get("peers", [])
        if not peers:
            return GLib.SOURCE_CONTINUE

        def _work():
            results = [
                check_peer_health(p["host"], p.get("port", 8765))
                for p in peers
            ]
            GLib.idle_add(self._set_peer_online, results)

        threading.Thread(target=_work, daemon=True).start()
        return GLib.SOURCE_CONTINUE

    def _set_peer_online(self, results: list[bool]) -> bool:
        self._peer_online = results
        self._apply_peer_dots()
        return GLib.SOURCE_REMOVE

    def _apply_peer_dots(self) -> None:
        for dot, online in zip(self._peer_status_labels, self._peer_online):
            colour = "#44ff88" if online else "#ff4444"
            dot.set_markup(f'<span foreground="{colour}" size="large">●</span>')

    def _on_force_sync(self, _btn) -> None:
        if _sync_manager:
            threading.Thread(target=_sync_manager.sync_all_now, daemon=True).start()
        self.toast("Sync triggered")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def toast(self, msg: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=msg, timeout=3))

    def _local_ip(self) -> str:
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

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        about_act = Gio.SimpleAction.new("about", None)
        about_act.connect("activate", self._on_about)
        self.add_action(about_act)

        quit_act = Gio.SimpleAction.new("quit", None)
        quit_act.connect("activate", lambda *_: self.quit())
        self.add_action(quit_act)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self) -> None:
        win = self.get_active_window()
        if not win:
            # Initialize the log BEFORE the window so _tick() can read it
            os.makedirs(DATA_DIR, exist_ok=True)
            awareness_log.initialize(LOG_PATH)
            win = SnifferOpsWindow(self)
            self._start_services(win)
        win.present()

    def _start_services(self, win: SnifferOpsWindow) -> None:
        global _sync_manager
        cfg = win._cfg
        awareness_log.start_server("0.0.0.0", cfg.get("port", 8765))

        _sync_manager = NodeSyncManager(
            awareness_log, NODE_ID, NODE_NAME, peers=cfg.get("peers", [])
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
                NetworkRtlSdrScanner(
                    parts[0], int(parts[1]) if len(parts) > 1 else 1234, _on_sdr
                ).start()
            else:
                from scanners.rtl_sdr_scanner import RtlSdrScanner
                RtlSdrScanner(_on_sdr).start()

        # Run one WiFi scan immediately so the table has data on launch
        if cfg.get("wifi", True):
            def _initial():
                try:
                    from scanners.wifi_scanner import scan_once
                    results = scan_once()
                    if results:
                        _on_wifi(results)
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
