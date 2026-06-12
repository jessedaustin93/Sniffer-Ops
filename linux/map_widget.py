"""
map_widget.py — GTK4 Cairo-based slippy map widget using CARTO dark tiles.
"""

import math
import os
import threading
import urllib.request
from itertools import cycle

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gdk, Gtk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TILE_SIZE = 256
MIN_ZOOM = 3
MAX_ZOOM = 18
DEFAULT_LAT = 39.5
DEFAULT_LON = -98.35
DEFAULT_ZOOM = 10

CARTO_SUBDOMAINS = cycle(["a", "b", "c"])
CARTO_SUBDOMAINS_LOCK = threading.Lock()
CARTO_URL_TEMPLATE = "https://{sub}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"

USER_AGENT = "SnifferOps/1.0 (map_widget.py; +https://github.com/example)"

# ---------------------------------------------------------------------------
# MapWidget
# ---------------------------------------------------------------------------

class MapWidget(Gtk.DrawingArea):
    """Cairo-backed slippy map widget for GTK4."""

    def __init__(self, tile_cache_dir: str):
        super().__init__()

        self._cache_dir = tile_cache_dir
        self._center_lat = DEFAULT_LAT
        self._center_lon = DEFAULT_LON
        self._zoom = DEFAULT_ZOOM

        self._markers: list = []

        # Tile surface cache: key -> cairo.ImageSurface | None (loading) | False (failed)
        self._tile_surfaces: dict = {}
        self._pending_fetches: set = set()
        self._tile_lock = threading.Lock()

        # Pan state
        self._drag_start_lat: float = DEFAULT_LAT
        self._drag_start_lon: float = DEFAULT_LON
        self._drag_start_x: float = 0.0
        self._drag_start_y: float = 0.0

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._on_draw)

        # Drag (pan)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        # Scroll (zoom)
        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        # Click (double-click zoom)
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_markers(self, markers: list) -> None:
        self._markers = markers
        self.queue_draw()

    def center_on(self, lat: float, lon: float, zoom: int | None = None) -> None:
        self._center_lat = lat
        self._center_lon = lon
        if zoom is not None:
            self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self.queue_draw()

    # ------------------------------------------------------------------
    # Tile coordinate math (Web Mercator)
    # ------------------------------------------------------------------

    @staticmethod
    def _lon_to_tile_x(lon: float, zoom: int) -> float:
        return (lon + 180.0) / 360.0 * (2 ** zoom)

    @staticmethod
    def _lat_to_tile_y(lat: float, zoom: int) -> float:
        lat_rad = math.radians(lat)
        return (
            (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
            / 2.0
            * (2 ** zoom)
        )

    @staticmethod
    def _tile_x_to_lon(tx: float, zoom: int) -> float:
        return tx / (2 ** zoom) * 360.0 - 180.0

    @staticmethod
    def _tile_y_to_lat(ty: float, zoom: int) -> float:
        return math.degrees(
            math.atan(math.sinh(math.pi * (1.0 - 2.0 * ty / (2 ** zoom))))
        )

    # ------------------------------------------------------------------
    # Widget ↔ lat/lon conversion
    # ------------------------------------------------------------------

    def _latlon_to_widget_xy(
        self, lat: float, lon: float, width: float, height: float
    ) -> tuple[float, float]:
        zoom = self._zoom
        cx = self._lon_to_tile_x(self._center_lon, zoom) * TILE_SIZE
        cy = self._lat_to_tile_y(self._center_lat, zoom) * TILE_SIZE
        px = self._lon_to_tile_x(lon, zoom) * TILE_SIZE
        py = self._lat_to_tile_y(lat, zoom) * TILE_SIZE
        wx = (px - cx) + width / 2.0
        wy = (py - cy) + height / 2.0
        return wx, wy

    def _widget_xy_to_latlon(
        self, x: float, y: float, width: float, height: float
    ) -> tuple[float, float]:
        zoom = self._zoom
        cx = self._lon_to_tile_x(self._center_lon, zoom) * TILE_SIZE
        cy = self._lat_to_tile_y(self._center_lat, zoom) * TILE_SIZE
        px = cx + (x - width / 2.0)
        py = cy + (y - height / 2.0)
        lon = self._tile_x_to_lon(px / TILE_SIZE, zoom)
        lat = self._tile_y_to_lat(py / TILE_SIZE, zoom)
        return lat, lon

    # ------------------------------------------------------------------
    # Tile helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_tile_key(z: int, x: int, y: int) -> str:
        return f"{z}/{x}/{y}"

    def _get_tile_surface(self, z: int, x: int, y: int):
        key = self._get_tile_key(z, x, y)

        with self._tile_lock:
            if key in self._tile_surfaces:
                return self._tile_surfaces[key]

        # Not in memory — check disk
        cache_path = os.path.join(self._cache_dir, f"{z}", f"{x}", f"{y}.png")
        if os.path.isfile(cache_path):
            try:
                surface = cairo.ImageSurface.create_from_png(cache_path)
                with self._tile_lock:
                    self._tile_surfaces[key] = surface
                return surface
            except Exception:
                pass  # fall through to async fetch

        # Not on disk — kick off async download
        self._fetch_tile_async(z, x, y)
        return None  # loading

    def _fetch_tile_async(self, z: int, x: int, y: int) -> None:
        key = self._get_tile_key(z, x, y)

        with self._tile_lock:
            if key in self._pending_fetches:
                return
            self._pending_fetches.add(key)
            # Mark as loading (None)
            self._tile_surfaces[key] = None

        def _worker():
            cache_path = os.path.join(self._cache_dir, str(z), str(x), f"{y}.png")
            try:
                with CARTO_SUBDOMAINS_LOCK:
                    sub = next(CARTO_SUBDOMAINS)
                url = CARTO_URL_TEMPLATE.format(sub=sub, z=z, x=x, y=y)
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                with open(cache_path, "wb") as f:
                    f.write(data)
                surface = cairo.ImageSurface.create_from_png(cache_path)
                with self._tile_lock:
                    self._tile_surfaces[key] = surface
            except Exception:
                with self._tile_lock:
                    self._tile_surfaces[key] = False
            finally:
                with self._tile_lock:
                    self._pending_fetches.discard(key)
                GLib.idle_add(self.queue_draw)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_fallback_tile(
        self, cr: cairo.Context, x: float, y: float, size: int
    ) -> None:
        # Dark background
        cr.save()
        cr.rectangle(x, y, size, size)
        cr.set_source_rgb(0x11 / 255, 0x18 / 255, 0x27 / 255)
        cr.fill()

        # Subtle grid
        cr.set_source_rgb(0x1f / 255, 0x2d / 255, 0x3d / 255)
        cr.set_line_width(0.5)
        step = 32
        for gx in range(0, size + 1, step):
            cr.move_to(x + gx, y)
            cr.line_to(x + gx, y + size)
        for gy in range(0, size + 1, step):
            cr.move_to(x, y + gy)
            cr.line_to(x + size, y + gy)
        cr.stroke()
        cr.restore()

    def _draw_marker(
        self, cr: cairo.Context, wx: float, wy: float, marker
    ) -> None:
        # Determine tier and style
        tier = getattr(marker, "tier", "gps")
        color = getattr(marker, "color", (1.0, 0.5, 0.0))
        count = getattr(marker, "count", 1)
        # signal_strength = getattr(marker, "signal_strength", None)

        cr.save()

        if isinstance(color, str):
            # Parse simple hex strings like "#rrggbb"
            color = color.lstrip("#")
            if len(color) == 6:
                r = int(color[0:2], 16) / 255
                g = int(color[2:4], 16) / 255
                b = int(color[4:6], 16) / 255
                color = (r, g, b)
            else:
                color = (1.0, 0.5, 0.0)

        r, g, b = color[0], color[1], color[2]

        if tier == "gps":
            radius = 6.0
            cr.arc(wx, wy, radius, 0, 2 * math.pi)
            cr.set_source_rgba(r, g, b, 1.0)
            cr.fill_preserve()
            cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            cr.set_line_width(1.5)
            cr.stroke()
        elif tier == "linked":
            radius = 5.0
            cr.arc(wx, wy, radius, 0, 2 * math.pi)
            cr.set_source_rgba(r, g, b, 0.55)
            cr.fill_preserve()
            cr.set_dash([4.0, 3.0])
            cr.set_source_rgba(r, g, b, 0.9)
            cr.set_line_width(1.5)
            cr.stroke()
            cr.set_dash([])
        else:
            # anchor or default
            radius = 4.0
            cr.arc(wx, wy, radius, 0, 2 * math.pi)
            cr.set_source_rgba(r, g, b, 0.35)
            cr.fill_preserve()
            cr.set_dash([2.0, 2.0])
            cr.set_source_rgba(r, g, b, 0.7)
            cr.set_line_width(1.0)
            cr.stroke()
            cr.set_dash([])

        # Count label
        if count > 1:
            label = str(count)
            cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(7.0)
            ext = cr.text_extents(label)
            cr.move_to(wx - ext.width / 2, wy + ext.height / 2)
            cr.show_text(label)

        cr.restore()

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def _cluster_markers(
        self, markers: list, width: float, height: float, threshold_px: float = 30.0
    ) -> list:
        """
        Group markers that are within threshold_px pixels of each other.
        Returns a list of pseudo-marker dicts with lat/lon/count/color/tier.
        """
        if not markers:
            return []

        points = []
        for m in markers:
            lat = getattr(m, "lat", None)
            lon = getattr(m, "lon", None)
            if lat is None or lon is None:
                continue
            wx, wy = self._latlon_to_widget_xy(lat, lon, width, height)
            points.append({"marker": m, "wx": wx, "wy": wy, "used": False})

        clusters = []
        for i, p in enumerate(points):
            if p["used"]:
                continue
            group = [p]
            p["used"] = True
            for j, q in enumerate(points):
                if q["used"]:
                    continue
                dx = p["wx"] - q["wx"]
                dy = p["wy"] - q["wy"]
                if math.hypot(dx, dy) <= threshold_px:
                    group.append(q)
                    q["used"] = True

            # Representative: centroid lat/lon, first marker's color/tier
            avg_lat = sum(
                getattr(item["marker"], "lat", 0) for item in group
            ) / len(group)
            avg_lon = sum(
                getattr(item["marker"], "lon", 0) for item in group
            ) / len(group)
            rep = group[0]["marker"]
            clusters.append(
                _ClusterMarker(
                    lat=avg_lat,
                    lon=avg_lon,
                    count=len(group),
                    color=getattr(rep, "color", (1.0, 0.5, 0.0)),
                    tier=getattr(rep, "tier", "gps"),
                )
            )
        return clusters

    # ------------------------------------------------------------------
    # Main draw function
    # ------------------------------------------------------------------

    def _on_draw(self, widget, cr: cairo.Context, width: int, height: int) -> None:
        # Background
        cr.set_source_rgb(0x02 / 255, 0x06 / 255, 0x17 / 255)
        cr.paint()

        zoom = self._zoom
        n_tiles = 2 ** zoom

        # Fractional tile coords of center
        cx_tile = self._lon_to_tile_x(self._center_lon, zoom)
        cy_tile = self._lat_to_tile_y(self._center_lat, zoom)

        # Pixel offset of the center tile's top-left corner within the widget
        center_px_x = width / 2.0 - (cx_tile - math.floor(cx_tile)) * TILE_SIZE
        center_px_y = height / 2.0 - (cy_tile - math.floor(cy_tile)) * TILE_SIZE

        # Range of tiles that cover the widget
        tile_x0 = int(math.floor(cx_tile)) - math.ceil(width / 2.0 / TILE_SIZE) - 1
        tile_y0 = int(math.floor(cy_tile)) - math.ceil(height / 2.0 / TILE_SIZE) - 1
        tile_x1 = int(math.floor(cx_tile)) + math.ceil(width / 2.0 / TILE_SIZE) + 1
        tile_y1 = int(math.floor(cy_tile)) + math.ceil(height / 2.0 / TILE_SIZE) + 1

        for ty in range(tile_y0, tile_y1 + 1):
            for tx in range(tile_x0, tile_x1 + 1):
                # Clamp y; wrap x
                if ty < 0 or ty >= n_tiles:
                    continue
                tx_wrapped = tx % n_tiles

                # Pixel position of this tile's top-left corner
                dx = tx - math.floor(cx_tile)
                dy = ty - math.floor(cy_tile)
                px = center_px_x + dx * TILE_SIZE
                py = center_px_y + dy * TILE_SIZE

                # Skip tiles fully outside viewport
                if px > width or py > height or px + TILE_SIZE < 0 or py + TILE_SIZE < 0:
                    continue

                surface = self._get_tile_surface(zoom, tx_wrapped, ty)
                if surface is None or surface is False:
                    self._draw_fallback_tile(cr, px, py, TILE_SIZE)
                else:
                    cr.set_source_surface(surface, px, py)
                    cr.paint()

        # Draw markers (clustered when zoomed out)
        if self._markers:
            if zoom < 10:
                draw_markers = self._cluster_markers(self._markers, width, height)
            else:
                draw_markers = self._markers

            for m in draw_markers:
                lat = getattr(m, "lat", None)
                lon = getattr(m, "lon", None)
                if lat is None or lon is None:
                    continue
                wx, wy = self._latlon_to_widget_xy(lat, lon, width, height)
                # Only draw if on screen (with a small margin)
                margin = 20
                if -margin <= wx <= width + margin and -margin <= wy <= height + margin:
                    self._draw_marker(cr, wx, wy, m)

        # Attribution text — bottom-right
        cr.save()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.0)
        attribution = "© OpenStreetMap contributors © CARTO"
        ext = cr.text_extents(attribution)
        margin = 6
        ax = width - ext.width - margin
        ay = height - margin

        # Semi-transparent dark backing pill
        pad = 3
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.55)
        cr.rectangle(
            ax - pad,
            ay - ext.height - pad,
            ext.width + pad * 2,
            ext.height + pad * 2,
        )
        cr.fill()

        cr.set_source_rgba(0.75, 0.75, 0.75, 0.85)
        cr.move_to(ax, ay)
        cr.show_text(attribution)
        cr.restore()

    # ------------------------------------------------------------------
    # Gesture handlers
    # ------------------------------------------------------------------

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, x: float, y: float) -> None:
        self._drag_start_lat = self._center_lat
        self._drag_start_lon = self._center_lon
        self._drag_start_x = x
        self._drag_start_y = y

    def _on_drag_update(
        self, gesture: Gtk.GestureDrag, dx: float, dy: float
    ) -> None:
        width = self.get_width()
        height = self.get_height()
        if width == 0 or height == 0:
            return

        # Compute new center = drag_start adjusted by (-dx, -dy)
        # Map start position to pixel, subtract delta, convert back
        zoom = self._zoom
        start_cx = self._lon_to_tile_x(self._drag_start_lon, zoom) * TILE_SIZE
        start_cy = self._lat_to_tile_y(self._drag_start_lat, zoom) * TILE_SIZE

        new_cx_px = start_cx - dx
        new_cy_px = start_cy - dy

        new_lon = self._tile_x_to_lon(new_cx_px / TILE_SIZE, zoom)
        new_lat = self._tile_y_to_lat(new_cy_px / TILE_SIZE, zoom)

        self._center_lat = new_lat
        self._center_lon = new_lon
        self.queue_draw()

    def _on_drag_end(
        self, gesture: Gtk.GestureDrag, dx: float, dy: float
    ) -> None:
        # Final update already applied in _on_drag_update
        pass

    def _on_scroll(
        self, ctrl: Gtk.EventControllerScroll, dx: float, dy: float
    ) -> bool:
        if dy > 0:
            new_zoom = self._zoom - 1
        else:
            new_zoom = self._zoom + 1
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))
        self.queue_draw()
        return True  # consume event

    def _on_click(
        self,
        gesture: Gtk.GestureClick,
        n_press: int,
        x: float,
        y: float,
    ) -> None:
        if n_press == 2:
            width = self.get_width()
            height = self.get_height()
            if width > 0 and height > 0:
                lat, lon = self._widget_xy_to_latlon(x, y, width, height)
                self._center_lat = lat
                self._center_lon = lon
                self._zoom = min(MAX_ZOOM, self._zoom + 1)
                self.queue_draw()


# ---------------------------------------------------------------------------
# Helper: lightweight cluster marker object
# ---------------------------------------------------------------------------

class _ClusterMarker:
    """Simple struct used by the clustering code."""

    __slots__ = ("lat", "lon", "count", "color", "tier", "signal_strength")

    def __init__(
        self,
        lat: float,
        lon: float,
        count: int = 1,
        color=(1.0, 0.5, 0.0),
        tier: str = "gps",
    ):
        self.lat = lat
        self.lon = lon
        self.count = count
        self.color = color
        self.tier = tier
        self.signal_strength = None
