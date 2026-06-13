"""
map_widget.py — MapLibre GL map widget via WebKit WebView.

Modeled on the deflock.org map: a dark basemap with clustered, colour-coded
points that split apart as you zoom in.  WebKit's WebGL engine (confirmed
WebGL 2.0 on this hardware) does all rendering in its own child processes, so
nothing heavy runs on the GTK main thread.

The page is written to ~/.snifferops/map.html and loaded via a file:// URL.
(WebKit's load_html() does not execute inline page scripts in this build, but a
real file:// page does — and file:// lets us reference the MapLibre library as
a relative <script src> instead of inlining ~800 KB into every page.)

This module:
  • Writes a self-contained map.html (MapLibre GL + CARTO dark raster basemap)
  • Feeds marker data as GeoJSON via evaluate_javascript()
  • Exposes set_markers() / center_on(), matching the old Cairo widget API

Why clustering: nearly all captures happen at a handful of physical spots, so
~1,600 markers otherwise stack into ~20 overlapping dots.  Clustering shows a
counted badge per spot that expands on zoom — exactly the deflock behaviour.
"""

import json
import os

# Ubuntu 23.10+/24.04 restrict unprivileged user namespaces via AppArmor
# (kernel.apparmor_restrict_unprivileged_userns=1).  That breaks the bwrap
# sandbox WebKitGTK spawns for its web process, so creating a WebView aborts
# the whole app ("Failed to fully launch dbus-proxy") and the window never
# opens.  We only ever load a local map.html + trusted CARTO map tiles — no
# untrusted web content — so disabling WebKit's process sandbox is safe here.
# Must be set before WebKit spawns any child process, i.e. before import.
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

# Eastern-US bounds  (VA / TN / KY / WV / NC + neighbours)
# MapLibre uses [lng, lat] order:  [[west, south], [east, north]]
MAX_BOUNDS = [[-91.0, 33.5], [-74.0, 40.5]]
MIN_ZOOM   = 6


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def _build_map_html() -> str:
    """Return the map page.  MapLibre is referenced relative to this file
    (expects ./maplibre/maplibre-gl.{js,css} as a sibling directory)."""
    bounds_json = json.dumps(MAX_BOUNDS)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="maplibre/maplibre-gl.css" rel="stylesheet">
<style>
html, body, #map {{
    margin: 0; padding: 0;
    width: 100%; height: 100%;
    background: #020617;
    overflow: hidden;
}}
/* deflock-style cluster badge */
.so-cluster {{
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%;
    color: #fff; font-weight: 700;
    font-family: 'Helvetica Neue', Arial, sans-serif;
    border: 2px solid rgba(255,255,255,0.85);
    box-shadow: 0 0 8px rgba(0,0,0,0.6);
    cursor: pointer;
    background: rgba(56,189,248,0.85);
}}
.maplibregl-popup-content {{
    background: #0f172a; color: #e2e8f0;
    border: 1px solid #334155; border-radius: 6px;
    font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 12px;
}}
.maplibregl-popup-tip {{ border-top-color: #0f172a; border-bottom-color: #0f172a; }}
</style>
</head>
<body>
<div id="map"></div>
<script src="maplibre/maplibre-gl.js"></script>
<script>
var CARTO_TILES = [
    'https://a.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}.png',
    'https://b.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}.png',
    'https://c.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}.png',
    'https://d.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}.png'
];

var style = {{
    version: 8,
    sources: {{
        'carto-dark': {{
            type: 'raster',
            tiles: CARTO_TILES,
            tileSize: 256,
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }}
    }},
    layers: [
        {{ id: 'basemap', type: 'raster', source: 'carto-dark',
           paint: {{ 'raster-fade-duration': 0 }} }}   // no tile crossfade → no idle CPU spin
    ]
}};

var map = new maplibregl.Map({{
    container: 'map',
    style: style,
    center: [{HOME_LON}, {HOME_LAT}],
    zoom: {HOME_ZOOM},
    minZoom: {MIN_ZOOM},
    maxZoom: 18,
    maxBounds: {bounds_json},
    attributionControl: false,
    fadeDuration: 0,           // no symbol fade animation → fewer render frames
    antialias: false,          // MSAA is pure cost on a software/weak GL path
    renderWorldCopies: false,  // don't render repeated earth copies
    refreshExpiredTiles: false,// don't re-fetch tiles in the background
    trackResize: true
}});
map.addControl(new maplibregl.NavigationControl({{ showCompass: false }}), 'top-right');
map.addControl(new maplibregl.AttributionControl({{ compact: true }}), 'bottom-right');

// Old integrated-GPU laptop (no real GPU): render the map at HALF resolution.
// WebGL re-rasterises every frame in software, so a quarter of the pixels is
// ~4x less work per frame — the single biggest win for smooth pan/zoom here.
// Cluster badges are DOM (CSS-pixel positioned) so they stay crisp.
if (typeof map.setPixelRatio === 'function') {{
    map.setPixelRatio(0.5);
}}

var EMPTY = {{ type: 'FeatureCollection', features: [] }};
var pendingData = null;          // markers that arrived before style load
var clusterMarkers = {{}};       // id -> maplibregl.Marker (DOM cluster badges)

map.on('load', function() {{
    map.addSource('signals', {{
        type: 'geojson',
        data: pendingData || EMPTY,
        cluster: true,
        clusterRadius: 60,
        // Cluster at EVERY zoom level (up to the map max).  Most devices were
        // seen at one spot, so without this, zooming in past clusterMaxZoom
        // dumps hundreds of overlapping dots on a single pixel — slow to draw
        // and useless to look at.  Keeping clustering on means co-located
        // devices stay a counted badge while genuinely separate ones split out.
        clusterMaxZoom: 18
    }});

    // Individual (unclustered) points — GL circle layer, coloured per type,
    // sized/faded per placement tier.
    map.addLayer({{
        id: 'points',
        type: 'circle',
        source: 'signals',
        filter: ['!', ['has', 'point_count']],
        paint: {{
            'circle-color': ['get', 'color'],
            'circle-radius': [
                'match', ['get', 'tier'],
                'gps', 6, 'linked', 5, 'anchor', 4,
                4
            ],
            'circle-opacity': [
                'match', ['get', 'tier'],
                'gps', 0.95, 'linked', 0.75, 'anchor', 0.5,
                0.6
            ],
            'circle-stroke-width': [
                'match', ['get', 'tier'], 'gps', 1.5, 0.8
            ],
            'circle-stroke-color': '#ffffff'
        }}
    }});

    // Click an individual point → popup with details.
    map.on('click', 'points', function(e) {{
        var p = e.features[0].properties;
        var coords = e.features[0].geometry.coordinates.slice();
        var html = '<b>' + (p.name || p.signal_type || 'Signal') + '</b>';
        if (p.signal_type) html += '<br>' + p.signal_type;
        if (p.tier)        html += '<br><span style="opacity:.7">placement: ' + p.tier + '</span>';
        new maplibregl.Popup().setLngLat(coords).setHTML(html).addTo(map);
    }});
    map.on('mouseenter', 'points', function(){{ map.getCanvas().style.cursor = 'pointer'; }});
    map.on('mouseleave', 'points', function(){{ map.getCanvas().style.cursor = ''; }});

    // Update cluster badges only when the map SETTLES (after a pan/zoom) or
    // when the clustered data changes — never on the per-frame 'render' event.
    // 'render' fires every frame, and mutating DOM markers inside it marks the
    // map dirty again → an infinite render→mutate→render loop that pegs a CPU
    // core forever and makes the whole window "not responding".
    map.on('moveend', scheduleClusterUpdate);
    map.on('data', function(e) {{
        if (e.sourceId === 'signals' && map.isSourceLoaded('signals')) {{
            scheduleClusterUpdate();
        }}
    }});
    pendingData = null;
}});

// Coalesce cluster-badge rebuilds — 'data' fires repeatedly while tiles load,
// and rebuilding DOM markers on every one of those is wasted work on slow HW.
var _clusterTimer = null;
function scheduleClusterUpdate() {{
    if (_clusterTimer) return;
    _clusterTimer = setTimeout(function() {{
        _clusterTimer = null;
        updateClusterMarkers();
    }}, 150);
}}

// deflock-style cluster badges as DOM markers (no glyph fonts needed → works
// fully offline).  Larger / busier clusters get a bigger, warmer badge.
function badgeStyle(count) {{
    var size, color;
    if (count >= 100)      {{ size = 46; color = 'rgba(245,158,11,0.9)'; }}
    else if (count >= 25)  {{ size = 40; color = 'rgba(56,189,248,0.9)'; }}
    else                   {{ size = 32; color = 'rgba(57,255,20,0.85)'; }}
    return {{ size: size, color: color }};
}}

function updateClusterMarkers() {{
    if (!map.getSource('signals') || !map.isSourceLoaded('signals')) return;
    var features = map.querySourceFeatures('signals');
    var seen = {{}};

    for (var i = 0; i < features.length; i++) {{
        var f = features[i];
        if (!f.properties.cluster) continue;
        var id = f.properties.cluster_id;
        seen[id] = true;
        if (clusterMarkers[id]) continue;   // reuse existing badge

        var count = f.properties.point_count;
        var st = badgeStyle(count);
        var el = document.createElement('div');
        el.className = 'so-cluster';
        el.style.width  = st.size + 'px';
        el.style.height = st.size + 'px';
        el.style.background = st.color;
        el.style.fontSize = (count >= 1000 ? 11 : 13) + 'px';
        el.textContent = count >= 1000 ? (Math.round(count/100)/10) + 'k' : count;

        (function(clusterId, coords) {{
            el.addEventListener('click', function() {{
                map.getSource('signals').getClusterExpansionZoom(clusterId)
                    .then(function(z) {{
                        map.easeTo({{ center: coords, zoom: z }});
                    }})
                    .catch(function() {{
                        map.easeTo({{ center: coords, zoom: map.getZoom() + 2 }});
                    }});
            }});
        }})(id, f.geometry.coordinates);

        clusterMarkers[id] = new maplibregl.Marker({{ element: el }})
            .setLngLat(f.geometry.coordinates)
            .addTo(map);
    }}

    // Remove badges for clusters no longer present.
    for (var key in clusterMarkers) {{
        if (!seen[key]) {{ clusterMarkers[key].remove(); delete clusterMarkers[key]; }}
    }}
}}

// ── Python-callable API ────────────────────────────────────────────────────
function setMarkers(geojson) {{
    var src = map.getSource('signals');
    if (src) {{
        src.setData(geojson);
        // clusters get rebuilt — drop stale badges so they re-render fresh
        for (var k in clusterMarkers) {{ clusterMarkers[k].remove(); }}
        clusterMarkers = {{}};
    }} else {{
        pendingData = geojson;   // style not loaded yet
    }}
}}

function centerOn(lat, lon, zoom) {{
    map.jumpTo({{ center: [lon, lat], zoom: zoom }});
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# MapWidget
# ---------------------------------------------------------------------------

class MapWidget(Gtk.Box):
    """MapLibre GL map (deflock-style clustering) embedded in a WebKit WebView."""

    def __init__(self, tile_cache_dir: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._markers: list = []
        self._ready         = False

        # The map page lives in the data dir alongside the maplibre/ library
        # folder, so the relative <script src="maplibre/..."> resolves.
        data_dir = os.path.dirname(tile_cache_dir)
        os.makedirs(data_dir, exist_ok=True)
        self._html_path = os.path.join(data_dir, "map.html")
        with open(self._html_path, "w", encoding="utf-8") as fh:
            fh.write(_build_map_html())

        settings = WebKit.Settings()
        settings.set_enable_javascript(True)
        settings.set_enable_webgl(True)               # MapLibre needs WebGL
        settings.set_enable_developer_extras(False)
        settings.set_enable_page_cache(True)
        # Let the file:// page load its sibling maplibre/ assets.
        try:
            settings.set_property("allow-file-access-from-file-urls", True)
        except Exception:
            pass
        # NOTE: do NOT force HardwareAccelerationPolicy.NEVER — that can disable
        # WebGL compositing.  Leave the default (ON_DEMAND) so MapLibre renders.

        self._webview = WebKit.WebView()
        self._webview.set_settings(settings)
        self._webview.set_hexpand(True)
        self._webview.set_vexpand(True)
        self._webview.connect("load-changed", self._on_load_changed)
        self.append(self._webview)

        self._webview.load_uri("file://" + self._html_path)

    # ------------------------------------------------------------------
    # Public API  (matches the old Cairo MapWidget interface)
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
