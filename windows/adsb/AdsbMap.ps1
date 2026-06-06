# ADS-B map output with a pluggable backend.
#
# The decoder (AdsbDecoder.ps1) produces aircraft objects. This module is the
# *rendering* half, deliberately decoupled so a different map can be plugged in:
#
#   1. Export-AircraftJson writes a stable JSON data contract to disk.
#   2. The configured backend ($script:AdsbMapBackend) consumes that JSON file.
#
# The default backend writes a self-contained Leaflet HTML page and opens it in
# the system browser. To plug in an offline map later, set $script:AdsbMapBackend
# to a scriptblock that takes the JSON path, e.g. before/after startup:
#
#   $script:AdsbMapBackend = { param($JsonPath) & "C:\MyOfflineMap.exe" $JsonPath }
#
# The JSON shape is the contract; it will not change shape without a version bump.

# Writes the aircraft list as JSON. Returns the path written.
function Export-AircraftJson {
    param(
        [object[]] $Aircraft,
        [string]   $Path
    )
    $payload = [pscustomobject][ordered]@{
        schema    = "snifferops.adsb/1"
        generated = (Get-Date).ToString("o")
        count     = @($Aircraft).Count
        aircraft  = @($Aircraft)
    }
    $json = $payload | ConvertTo-Json -Depth 6
    Set-Content -Path $Path -Value $json -Encoding UTF8
    return $Path
}

# Default backend: build a Leaflet map HTML from the JSON and open it.
function New-AdsbLeafletMap {
    param(
        [string] $JsonPath,
        [string] $HtmlPath
    )

    $json = Get-Content -Path $JsonPath -Raw

    # The page reads the embedded JSON, plots positioned aircraft as markers, and
    # lists position-less contacts in a side panel. Tiles come from OpenStreetMap
    # (needs internet) — swap the tile URL for an offline tile source if desired.
    $html = @"
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>SnifferOps ADS-B</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body { margin:0; height:100%; font-family:Consolas,monospace; background:#020617; color:#E5E7EB; }
  #wrap { display:flex; height:100%; }
  #map { flex:1; }
  #side { width:300px; overflow-y:auto; padding:12px; box-sizing:border-box; background:#0b1220; }
  h1 { font-size:16px; color:#38bdf8; margin:0 0 8px; }
  .meta { font-size:11px; color:#94a3b8; margin-bottom:10px; }
  .ac { border-bottom:1px solid #1e293b; padding:6px 0; font-size:12px; }
  .ac b { color:#fbbf24; }
  .nopos { color:#64748b; }
</style>
</head>
<body>
<div id="wrap">
  <div id="map"></div>
  <div id="side">
    <h1>ADS-B CONTACTS</h1>
    <div class="meta" id="meta"></div>
    <div id="list"></div>
  </div>
</div>
<script>
  var DATA = $json;
  var map = L.map('map').setView([39.8, -98.6], 4);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '(c) OpenStreetMap'
  }).addTo(map);

  var acs = (DATA && DATA.aircraft) ? DATA.aircraft : [];
  var positioned = acs.filter(function(a) { return a.Lat != null && a.Lon != null; });
  document.getElementById('meta').textContent =
    acs.length + ' contacts  |  ' + positioned.length + ' mapped  |  ' + (DATA.generated || '');

  var bounds = [];
  var list = document.getElementById('list');
  acs.forEach(function(a) {
    var label = (a.Callsign && a.Callsign.length ? a.Callsign : a.Icao);
    var div = document.createElement('div');
    div.className = 'ac';
    var bits = ['<b>' + label + '</b> (' + a.Icao + ')'];
    if (a.Altitude != null) bits.push(a.Altitude + ' ft');
    if (a.SpeedKt != null) bits.push(a.SpeedKt + ' kt');
    if (a.TrackDeg != null) bits.push(a.TrackDeg + '&deg;');
    if (a.Lat == null) bits.push('<span class="nopos">no position</span>');
    div.innerHTML = bits.join(' &middot; ');
    list.appendChild(div);

    if (a.Lat != null && a.Lon != null) {
      var m = L.marker([a.Lat, a.Lon]).addTo(map);
      m.bindPopup('<b>' + label + '</b><br>' + a.Icao +
        (a.Altitude != null ? '<br>' + a.Altitude + ' ft' : '') +
        (a.SpeedKt != null ? '<br>' + a.SpeedKt + ' kt' : ''));
      bounds.push([a.Lat, a.Lon]);
    }
  });
  if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 10 });
  if (!bounds.length && acs.length) {
    var div = document.createElement('div');
    div.className = 'ac nopos';
    div.textContent = 'No map points yet: ADS-B position needs a verified even/odd position pair from the same aircraft.';
    list.insertBefore(div, list.firstChild);
  }
</script>
</body>
</html>
"@

    Set-Content -Path $HtmlPath -Value $html -Encoding UTF8
    return $HtmlPath
}

# Top-level entry: persist the JSON contract, then hand it to the active backend.
function Invoke-AdsbMapBackend {
    param(
        [object[]] $Aircraft,
        [string]   $OutputDir
    )
    $jsonPath = Join-Path $OutputDir "adsb-aircraft.json"
    [void](Export-AircraftJson -Aircraft $Aircraft -Path $jsonPath)

    if ($script:AdsbMapBackend) {
        # User-supplied backend (e.g. an offline map program).
        & $script:AdsbMapBackend $jsonPath
        return $jsonPath
    }

    # Default backend: Leaflet HTML + system browser.
    $htmlPath = Join-Path $OutputDir "adsb-map.html"
    [void](New-AdsbLeafletMap -JsonPath $jsonPath -HtmlPath $htmlPath)
    Start-Process $htmlPath
    return $htmlPath
}
