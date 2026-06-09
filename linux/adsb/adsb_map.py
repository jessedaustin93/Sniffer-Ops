"""
ADS-B Leaflet map generator — ported from AdsbMap.ps1.
Outputs a self-contained HTML file with OpenStreetMap tiles.
"""

import json


def generate_map_html(aircraft_list: list[dict], output_path: str) -> str:
    """
    Generate a self-contained Leaflet HTML map.
    aircraft_list: list of dicts with keys: icao, callsign, latitude, longitude,
                   altitude_ft, speed_kts, heading_deg
    Returns the path written.
    """
    features = []
    for ac in aircraft_list:
        lat = ac.get("latitude")
        lon = ac.get("longitude")
        if lat is None or lon is None:
            continue
        label = ac.get("callsign") or ac.get("icao", "?")
        popup_lines = [
            f"<b>{label}</b>",
            f"ICAO: {ac.get('icao', '')}",
        ]
        if ac.get("altitude_ft") is not None:
            popup_lines.append(f"Alt: {ac['altitude_ft']:,} ft")
        if ac.get("speed_kts") is not None:
            popup_lines.append(f"Speed: {ac['speed_kts']} kts")
        if ac.get("heading_deg") is not None:
            popup_lines.append(f"Hdg: {ac['heading_deg']}&deg;")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"popup": "<br>".join(popup_lines), "label": label},
        })

    geojson = json.dumps({"type": "FeatureCollection", "features": features})

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>SnifferOps ADS-B Map</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
body {{margin:0;background:#0a0a0a;color:#00ff88;font-family:monospace;}}
#map {{width:100vw;height:100vh;}}
#title {{position:absolute;top:12px;left:50%;transform:translateX(-50%);
         z-index:1000;background:rgba(0,0,0,.7);padding:6px 16px;
         border:1px solid #00ff88;font-size:14px;}}
</style>
</head>
<body>
<div id="title">SnifferOps &mdash; ADS-B ({len(features)} aircraft)</div>
<div id="map"></div>
<script>
var map = L.map('map').setView([39.5,-98.35],5);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{
  maxZoom:18,attribution:'&copy; OpenStreetMap contributors'
}}).addTo(map);

var planeIcon = L.divIcon({{
  className:'',
  html:'<svg width="20" height="20" viewBox="-10 -10 20 20"><polygon points="0,-9 3,3 0,1 -3,3" fill="#00ff88" stroke="#000" stroke-width="1"/></svg>',
  iconSize:[20,20],iconAnchor:[10,10]
}});

var data = {geojson};
data.features.forEach(function(f){{
  var c = f.geometry.coordinates;
  var m = L.marker([c[1],c[0]],{{icon:planeIcon}}).addTo(map);
  m.bindPopup(f.properties.popup);
}});
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return output_path
