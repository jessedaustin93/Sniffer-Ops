"""
map_widget.py — Leaflet map widget via WebKit WebView (LOW-END / NO-GPU build).

This is the Leaflet variant, chosen for machines without a usable GPU.  Unlike
MapLibre (which rasterises every frame through WebGL — slow in software), Leaflet
renders the basemap as plain <img> tiles moved with CSS transforms, which the
compositor handles as cheap 2D work.  On an old integrated-graphics laptop this
is noticeably smoother.

The deflock.org look is preserved: dark CARTO basemap, clustered counted badges
(via the Leaflet.markercluster plugin), and clickable per-type coloured dots.

The full-featured MapLibre/WebGL version is kept alongside as
``map_widget_maplibre.py`` — swap the import in snifferops_gui.py to use it on a
machine with a real GPU.

Page is written to ~/.snifferops/map.html and loaded via file:// (WebKit's
load_html() does not run inline page scripts in this build; a real file:// page
does, and lets us reference the Leaflet libs as relative <script src>).
"""

import json
import os

# Ubuntu 23.10+/24.04 restrict unprivileged user namespaces via AppArmor, which
# breaks the bwrap sandbox WebKitGTK spawns for its web process and aborts the
# whole app.  We only load a local map.html + trusted CARTO tiles, so disabling
# WebKit's process sandbox is safe.  Must be set before WebKit spawns anything.
os.environ.setdefault("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS", "1")

import gi
gi.require_version("Gtk",    "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, WebKit, GLib

# ---------------------------------------------------------------------------
# Signal colours  (keep in sync with map_placement.SIGNAL_COLORS)
# ---------------------------------------------------------------------------
SIGNAL_COLORS = {
    "WIFI":      "#39FF14",
    "BLUETOOTH": "#00BFFF",
    "BLE":       "#38BDF8",
    "CELLULAR":  "#F59E0B",
    "RTL_SDR":   "#8B5CF6",
}
DEFAULT_COLOR = "#9CA3AF"

# Default map home — generic in-region placeholder (Knoxville, TN).  The app
# re-centers via center_on() using the per-install location from config.json,
# so no real/personal location is hardcoded here.
HOME_LAT  = 35.9606
HOME_LON  = -83.9207
HOME_ZOOM = 11

# Eastern-US bounds (VA / TN / KY / WV / NC + neighbours).
# Leaflet uses [lat, lng] order:  [[south, west], [north, east]]
MAX_BOUNDS = [[33.5, -91.0], [40.5, -74.0]]
MIN_ZOOM   = 6


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def _build_map_html() -> str:
    """Return the map page.  Leaflet + markercluster are referenced relative to
    this file (expects ./leaflet/ as a sibling directory)."""
    bounds_json = json.dumps(MAX_BOUNDS)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="leaflet/leaflet.css" rel="stylesheet">
<link href="leaflet/MarkerCluster.css" rel="stylesheet">
<style>
html, body, #map {{
    margin: 0; padding: 0;
    width: 100%; height: 100%;
    background: #020617;
}}
.leaflet-container {{ background: #020617; outline: none; }}
/* deflock-style cluster badge */
.so-cluster {{
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%;
    color: #fff; font-weight: 700;
    font-family: 'Helvetica Neue', Arial, sans-serif;
    border: 2px solid rgba(255,255,255,0.85);
    box-shadow: 0 0 8px rgba(0,0,0,0.6);
}}
.leaflet-popup-content-wrapper {{
    background: #0f172a; color: #e2e8f0;
    border: 1px solid #334155; border-radius: 6px;
}}
.leaflet-popup-content {{ font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 12px; }}
.leaflet-popup-tip {{ background: #0f172a; }}
</style>
</head>
<body>
<div id="map"></div>
<script src="leaflet/leaflet.js"></script>
<script src="leaflet/leaflet.markercluster.js"></script>
<script>
var map = L.map('map', {{
    center: [{HOME_LAT}, {HOME_LON}],
    zoom: {HOME_ZOOM},
    minZoom: {MIN_ZOOM},
    maxZoom: 18,
    maxBounds: {bounds_json},
    maxBoundsViscosity: 1.0,
    preferCanvas: true,        // draw vector dots on one <canvas>, not many DOM nodes
    zoomControl: true
}});

L.tileLayer(
    'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}.png',
    {{
        subdomains: 'abcd',
        maxZoom: 18,
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
    }}
).addTo(map);

function badgeStyle(count) {{
    if (count >= 100)     return {{ size: 46, color: 'rgba(245,158,11,0.9)' }};
    if (count >= 25)      return {{ size: 40, color: 'rgba(56,189,248,0.9)' }};
    return {{ size: 32, color: 'rgba(57,255,20,0.85)' }};
}}

var clusterGroup = L.markerClusterGroup({{
    maxClusterRadius: 60,
    chunkedLoading: true,          // add markers in chunks → never freezes the UI
    removeOutsideVisibleBounds: true,
    spiderfyOnMaxZoom: false,      // don't fan out hundreds of co-located dots
    showCoverageOnHover: false,
    iconCreateFunction: function(cluster) {{
        var count = cluster.getChildCount();
        var st = badgeStyle(count);
        var txt = count >= 1000 ? (Math.round(count / 100) / 10) + 'k' : count;
        var fs  = count >= 1000 ? 11 : 13;
        return L.divIcon({{
            html: '<div class="so-cluster" style="width:' + st.size + 'px;height:' +
                  st.size + 'px;background:' + st.color + ';font-size:' + fs + 'px">' +
                  txt + '</div>',
            className: '',
            iconSize: [st.size, st.size]
        }});
    }}
}});
map.addLayer(clusterGroup);

// ── Python-callable API ────────────────────────────────────────────────────
function setMarkers(geojson) {{
    clusterGroup.clearLayers();
    var markers = [];
    var feats = geojson.features || [];
    for (var i = 0; i < feats.length; i++) {{
        var f = feats[i];
        var c = f.geometry.coordinates;     // [lon, lat]
        var p = f.properties || {{}};
        var color   = p.color || '#9CA3AF';
        var opacity = p.tier === 'gps' ? 0.95 : (p.tier === 'linked' ? 0.75 : 0.5);
        var radius  = p.tier === 'gps' ? 6    : (p.tier === 'linked' ? 5    : 4);
        var m = L.circleMarker([c[1], c[0]], {{
            radius:      radius,
            color:       p.tier === 'gps' ? '#ffffff' : color,
            weight:      p.tier === 'gps' ? 1.5 : 0.8,
            opacity:     opacity,
            fillColor:   color,
            fillOpacity: opacity * 0.9
        }});
        var label = p.name || p.signal_type || 'Signal';
        var html = '<b>' + label + '</b>';
        if (p.signal_type) html += '<br>' + p.signal_type;
        if (p.tier)        html += '<br><span style="opacity:.7">placement: ' + p.tier + '</span>';
        m.bindPopup(html);
        markers.push(m);
    }}
    clusterGroup.addLayers(markers);   // bulk + chunked add
}}

function centerOn(lat, lon, zoom) {{
    map.setView([lat, lon], zoom);
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# MapWidget
# ---------------------------------------------------------------------------

class MapWidget(Gtk.Box):
    """Leaflet map (deflock-style clustering) embedded in a WebKit WebView."""

    def __init__(self, tile_cache_dir: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._markers: list = []
        self._ready         = False

        data_dir = os.path.dirname(tile_cache_dir)
        os.makedirs(data_dir, exist_ok=True)
        self._html_path = os.path.join(data_dir, "map.html")
        with open(self._html_path, "w", encoding="utf-8") as fh:
            fh.write(_build_map_html())

        settings = WebKit.Settings()
        settings.set_enable_javascript(True)
        settings.set_enable_developer_extras(False)
        settings.set_enable_page_cache(True)
        try:
            settings.set_property("allow-file-access-from-file-urls", True)
        except Exception:
            pass

        self._webview = WebKit.WebView()
        self._webview.set_settings(settings)
        self._webview.set_hexpand(True)
        self._webview.set_vexpand(True)
        self._webview.connect("load-changed", self._on_load_changed)
        self.append(self._webview)

        self._webview.load_uri("file://" + self._html_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_markers(self, markers: list) -> None:
        self._markers = markers
        if self._ready:
            self._inject_markers()

    def center_on(self, lat: float, lon: float, zoom: int | None = None) -> None:
        if not self._ready:
            return
        z = zoom if zoom is not None else HOME_ZOOM
        self._js(f"centerOn({lat}, {lon}, {z})")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_load_changed(self, webview, event) -> None:
        if event == WebKit.LoadEvent.FINISHED:
            self._ready = True
            if self._markers:
                GLib.idle_add(self._inject_markers)

    def _inject_markers(self) -> bool:
        features = []
        for m in self._markers:
            lat = getattr(m, "lat", None)
            lon = getattr(m, "lon", None)
            if lat is None or lon is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "color":       getattr(m, "color",       DEFAULT_COLOR),
                    "tier":        getattr(m, "tier",        "anchor"),
                    "name":        getattr(m, "name",        ""),
                    "signal_type": getattr(m, "signal_type", ""),
                    "count":       getattr(m, "count",       1),
                },
            })
        geojson = {"type": "FeatureCollection", "features": features}
        self._js(f"setMarkers({json.dumps(geojson)})")
        return GLib.SOURCE_REMOVE

    def _js(self, script: str) -> None:
        """Fire-and-forget JavaScript evaluation."""
        self._webview.evaluate_javascript(script, -1, None, None, None, None, None)
