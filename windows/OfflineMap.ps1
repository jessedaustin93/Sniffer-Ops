# In-app offline awareness map.
#
# Renders awareness-log signals over a real map background: standard slippy
# tiles (dark CARTO/OpenStreetMap style) downloaded once when online and
# cached under data\map-tiles\, then rendered from disk forever after - the
# map keeps working fully offline wherever you have already looked. With no
# cached tiles at all it falls back to a plain coordinate grid.
#
# Signal placement is tiered:
#   gps    - the signal itself has GPS-located sightings (phone GPS).
#   linked - no own GPS, but the same node reported GPS fixes for other signals
#            close in time; the signal is placed from those co-seen fixes.
#   anchor - no time-correlated fix; placed at the observing node's usual area
#            (average of that node's GPS fixes, or of GPS-placed signals the
#            node also sees).
#   unplaced - nothing GPS-related ever observed alongside it.
#
# Get-OfflineMapPlacements and the Web Mercator helpers are pure (no WPF) so
# Test-OfflineMap.ps1 can verify them headlessly.

$script:OfflineMapWindow = $null
$script:OfflineMapLinkWindowMinutes = 20.0
$script:OfflineMapTileUrlTemplate = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
$script:OfflineMapTileCacheRoot = Join-Path (Split-Path -Parent $PSScriptRoot) "data\map-tiles\dark"
$script:OfflineMapAttributionText = "(c) OpenStreetMap contributors (c) CARTO - tiles cached for offline use"
$script:OfflineMapHttpClient = $null

function ConvertTo-OfflineMapTime {
    param([object] $Value)

    if ($null -eq $Value) { return $null }
    $text = ([string]$Value).Trim()
    if (-not $text) { return $null }
    $parsed = [datetime]::MinValue
    $styles = [System.Globalization.DateTimeStyles]::RoundtripKind
    if ([datetime]::TryParse($text, [System.Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$parsed)) {
        return $parsed.ToUniversalTime()
    }
    return $null
}

function Get-OfflineMapSightingFix {
    # A "fix" is the node's own position at sighting time. Prefer the explicit
    # node coordinates; older sightings only carry the merged signal position,
    # which fell back to the node position anyway.
    param([object] $Sighting)

    $lat = ConvertTo-AwarenessNumber $Sighting.NodeLatitude
    $lon = ConvertTo-AwarenessNumber $Sighting.NodeLongitude
    if ($null -eq $lat -or $null -eq $lon) {
        $lat = ConvertTo-AwarenessNumber $Sighting.Latitude
        $lon = ConvertTo-AwarenessNumber $Sighting.Longitude
    }
    if ($null -eq $lat -or $null -eq $lon) { return $null }
    $at = ConvertTo-OfflineMapTime $Sighting.At
    if ($null -eq $at) { return $null }
    return [pscustomobject][ordered]@{
        NodeId = [string]$Sighting.NodeId
        At = $at
        Latitude = $lat
        Longitude = $lon
    }
}

function Get-OfflineMapNodeFixes {
    param([object[]] $Profiles)

    $fixes = @{}
    foreach ($profile in @($Profiles)) {
        foreach ($sighting in @($profile.Sightings)) {
            $fix = Get-OfflineMapSightingFix -Sighting $sighting
            if ($null -eq $fix -or -not $fix.NodeId) { continue }
            if (-not $fixes.ContainsKey($fix.NodeId)) {
                $fixes[$fix.NodeId] = New-Object System.Collections.ArrayList
            }
            [void]$fixes[$fix.NodeId].Add($fix)
        }
    }
    return $fixes
}

function Get-OfflineMapProfileNodeIds {
    param([object] $Profile)

    $ids = @()
    if ($Profile.PSObject.Properties["NodeIds"]) {
        $ids = @($Profile.NodeIds | ForEach-Object { [string]$_ } | Where-Object { $_ })
    }
    foreach ($sighting in @($Profile.Sightings)) {
        $nodeId = [string]$sighting.NodeId
        if ($nodeId -and $ids -notcontains $nodeId) { $ids += $nodeId }
    }
    return @($ids)
}

function Get-OfflineMapPlacements {
    param(
        [object[]] $Profiles,
        [double] $LinkWindowMinutes = 0.0
    )

    if ($LinkWindowMinutes -le 0) { $LinkWindowMinutes = $script:OfflineMapLinkWindowMinutes }
    $profiles = @($Profiles)
    $nodeFixes = Get-OfflineMapNodeFixes -Profiles $profiles
    $placements = @()

    # Pass 1: retain distinct own-GPS sightings so movement stays visible,
    # then place signals without GPS from time-correlated fixes.
    foreach ($profile in $profiles) {
        $geo = @()
        foreach ($sighting in @($profile.Sightings)) {
            $lat = ConvertTo-AwarenessNumber $sighting.Latitude
            $lon = ConvertTo-AwarenessNumber $sighting.Longitude
            if ($null -ne $lat -and $null -ne $lon) {
                $existingPoint = @($geo | Where-Object {
                    (Get-AwarenessDistanceMeters -Lat1 $_.Latitude -Lon1 $_.Longitude -Lat2 $lat -Lon2 $lon) -lt 25.0
                } | Select-Object -First 1)
                if ($existingPoint.Count -eq 0) {
                    $geo += [pscustomobject]@{
                        Latitude = $lat
                        Longitude = $lon
                        At = $sighting.At
                    }
                }
            }
        }

        $tier = "unplaced"
        $lat = $null
        $lon = $null
        $note = "No GPS data was ever synced alongside this signal."

        if ($geo.Count -gt 0) {
            $pointNumber = 0
            foreach ($point in $geo) {
                $pointNumber++
                $placements += [pscustomobject][ordered]@{
                    Key = "$($profile.Key)|gps-$pointNumber"
                    ProfileKey = $profile.Key
                    Name = $profile.Name
                    Type = $profile.Type
                    SpecificType = $profile.SpecificType
                    Class = $profile.Class
                    LastSeen = $profile.LastSeen
                    SeenCount = $profile.SeenCount
                    LastSignal = $profile.LastSignal
                    NodeIds = @(Get-OfflineMapProfileNodeIds -Profile $profile)
                    PlacementTier = "gps"
                    Latitude = $point.Latitude
                    Longitude = $point.Longitude
                    PlacementNote = "Phone GPS sighting $pointNumber of $($geo.Count), recorded $($point.At)."
                }
            }
            continue
        } else {
            # Correlate each sighting with the nearest-in-time GPS fix that the
            # same node reported for any other signal.
            $weightSum = 0.0
            $latSum = 0.0
            $lonSum = 0.0
            $matched = 0
            foreach ($sighting in @($profile.Sightings)) {
                $nodeId = [string]$sighting.NodeId
                if (-not $nodeId -or -not $nodeFixes.ContainsKey($nodeId)) { continue }
                $at = ConvertTo-OfflineMapTime $sighting.At
                if ($null -eq $at) { continue }
                $best = $null
                $bestMinutes = 0.0
                foreach ($fix in $nodeFixes[$nodeId]) {
                    $minutes = [Math]::Abs(($fix.At - $at).TotalMinutes)
                    if ($minutes -gt $LinkWindowMinutes) { continue }
                    if ($null -eq $best -or $minutes -lt $bestMinutes) {
                        $best = $fix
                        $bestMinutes = $minutes
                    }
                }
                if ($null -ne $best) {
                    $weight = 1.0 / (1.0 + $bestMinutes)
                    $latSum += $best.Latitude * $weight
                    $lonSum += $best.Longitude * $weight
                    $weightSum += $weight
                    $matched++
                }
            }
            if ($weightSum -gt 0) {
                $tier = "linked"
                $lat = $latSum / $weightSum
                $lon = $lonSum / $weightSum
                $note = "Inferred: $matched sighting(s) matched GPS fixes the same node reported within $([int]$LinkWindowMinutes) min."
            }
        }

        $placements += [pscustomobject][ordered]@{
            Key = $profile.Key
            ProfileKey = $profile.Key
            Name = $profile.Name
            Type = $profile.Type
            SpecificType = $profile.SpecificType
            Class = $profile.Class
            LastSeen = $profile.LastSeen
            SeenCount = $profile.SeenCount
            LastSignal = $profile.LastSignal
            NodeIds = @(Get-OfflineMapProfileNodeIds -Profile $profile)
            PlacementTier = $tier
            Latitude = $lat
            Longitude = $lon
            PlacementNote = $note
        }
    }

    # Pass 2: node anchors. A node's anchor is the average of its own GPS
    # fixes; a node that never had GPS (e.g. the Windows PC) borrows the
    # average position of already-placed signals it also sees.
    $anchors = @{}
    $allNodeIds = @()
    foreach ($placement in $placements) {
        foreach ($nodeId in $placement.NodeIds) {
            if ($allNodeIds -notcontains $nodeId) { $allNodeIds += $nodeId }
        }
    }
    foreach ($nodeId in $allNodeIds) {
        if ($nodeFixes.ContainsKey($nodeId) -and @($nodeFixes[$nodeId]).Count -gt 0) {
            $nodeFixList = @($nodeFixes[$nodeId])
            $anchors[$nodeId] = [pscustomobject]@{
                Latitude = ($nodeFixList | Measure-Object -Property Latitude -Average).Average
                Longitude = ($nodeFixList | Measure-Object -Property Longitude -Average).Average
                Source = "this node's own GPS fixes"
            }
            continue
        }
        $coSeen = @($placements | Where-Object { $_.PlacementTier -in @("gps", "linked") -and @($_.NodeIds) -contains $nodeId })
        if ($coSeen.Count -gt 0) {
            $anchors[$nodeId] = [pscustomobject]@{
                Latitude = ($coSeen | Measure-Object -Property Latitude -Average).Average
                Longitude = ($coSeen | Measure-Object -Property Longitude -Average).Average
                Source = "GPS-placed signals this node also sees"
            }
        }
    }

    foreach ($placement in @($placements | Where-Object { $_.PlacementTier -eq "unplaced" })) {
        $hits = @()
        $sources = @()
        foreach ($nodeId in $placement.NodeIds) {
            if ($anchors.ContainsKey($nodeId)) {
                $hits += $anchors[$nodeId]
                if ($sources -notcontains $anchors[$nodeId].Source) { $sources += $anchors[$nodeId].Source }
            }
        }
        if ($hits.Count -gt 0) {
            $placement.PlacementTier = "anchor"
            $placement.Latitude = (@($hits) | Measure-Object -Property Latitude -Average).Average
            $placement.Longitude = (@($hits) | Measure-Object -Property Longitude -Average).Average
            $placement.PlacementNote = "Inferred: placed at the usual area of its observing node(s) ($($sources -join '; '))."
        }
    }

    return @($placements)
}

function Get-OfflineMapTypeColor {
    param([string] $Type)

    switch (([string]$Type).Trim().ToUpperInvariant()) {
        "WIFI" { return "#39FF14" }
        "BLUETOOTH" { return "#00BFFF" }
        "BLE" { return "#38BDF8" }
        "CELLULAR" { return "#F59E0B" }
        "RTL_SDR" { return "#8B5CF6" }
        default { return "#E5E7EB" }
    }
}

# ---------------------------------------------------------------------------
# Web Mercator math (standard slippy-tile projection). Pure and testable.
# ---------------------------------------------------------------------------

function Get-OfflineMapWorldPixel {
    # Lat/lon -> absolute pixel position in the world map at a (possibly
    # fractional) zoom level, using 256 px tiles.
    param([double] $Lat, [double] $Lon, [double] $Zoom)

    $n = 256.0 * [Math]::Pow(2.0, $Zoom)
    $clampedLat = [Math]::Max(-85.05112878, [Math]::Min(85.05112878, $Lat))
    $latRad = $clampedLat * [Math]::PI / 180.0
    $x = ($Lon + 180.0) / 360.0 * $n
    $y = (1.0 - [Math]::Log([Math]::Tan($latRad) + 1.0 / [Math]::Cos($latRad)) / [Math]::PI) / 2.0 * $n
    return @($x, $y)
}

function Get-OfflineMapLatLon {
    # Inverse of Get-OfflineMapWorldPixel.
    param([double] $X, [double] $Y, [double] $Zoom)

    $n = 256.0 * [Math]::Pow(2.0, $Zoom)
    $lon = $X / $n * 360.0 - 180.0
    $lat = [Math]::Atan([Math]::Sinh([Math]::PI * (1.0 - 2.0 * $Y / $n))) * 180.0 / [Math]::PI
    return @($lat, $lon)
}

function Get-OfflineMapMetersPerPixel {
    param([double] $Lat, [double] $Zoom)
    return 156543.03392 * [Math]::Cos($Lat * [Math]::PI / 180.0) / [Math]::Pow(2.0, $Zoom)
}

# ---------------------------------------------------------------------------
# Tile cache: download once when online, serve from disk afterwards.
# ---------------------------------------------------------------------------

function Get-OfflineMapTilePath {
    param([int] $Z, [int] $X, [int] $Y)
    return Join-Path $script:OfflineMapTileCacheRoot "$Z\$X\$Y.png"
}

function Request-OfflineMapTile {
    # Ensures the tile is cached on disk. Returns $true when the file exists
    # afterwards. Never throws; a download failure just returns $false so the
    # caller can back off into offline mode.
    param([int] $Z, [int] $X, [int] $Y)

    $path = Get-OfflineMapTilePath -Z $Z -X $X -Y $Y
    if (Test-Path -LiteralPath $path) { return $true }

    try {
        if (-not $script:OfflineMapHttpClient) {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
            $client = New-Object System.Net.Http.HttpClient
            $client.Timeout = [TimeSpan]::FromSeconds(4)
            $client.DefaultRequestHeaders.UserAgent.ParseAdd("SnifferOps-Windows/1.0 (personal offline tile cache)")
            $script:OfflineMapHttpClient = $client
        }
        $sub = @("a", "b", "c", "d")[(($X + $Y) % 4)]
        $url = $script:OfflineMapTileUrlTemplate.Replace("{s}", $sub).Replace("{z}", [string]$Z).Replace("{x}", [string]$X).Replace("{y}", [string]$Y)
        $bytes = $script:OfflineMapHttpClient.GetByteArrayAsync($url).Result
        if (-not $bytes -or $bytes.Length -lt 100) { return $false }
        $dir = Split-Path -Parent $path
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $temp = "$path.tmp"
        [System.IO.File]::WriteAllBytes($temp, $bytes)
        Move-Item -LiteralPath $temp -Destination $path -Force
        return $true
    } catch {
        return $false
    }
}

# ---------------------------------------------------------------------------
# Map window (WPF). Everything below is render-only; no placement logic here.
# All mutable view state lives in the $view hashtable so the GetNewClosure'd
# handlers share it by reference after this function returns.
# ---------------------------------------------------------------------------

function Show-OfflineMapWindow {
    if ($script:OfflineMapWindow) {
        if ($script:OfflineMapWindow.IsLoaded) {
            [void]$script:OfflineMapWindow.Activate()
            return
        }
        $script:OfflineMapWindow = $null
    }

    # Local copies: $script: variables do not resolve inside the
    # GetNewClosure'd event handlers below (they look in the closure's own
    # module scope), so everything the closures need must be a captured local.
    $brush = $script:BrushConverter
    $attributionText = $script:OfflineMapAttributionText

    $win = New-Object System.Windows.Window
    $win.Title = "SnifferOps - Offline Awareness Map"
    $win.Width = 1060
    $win.Height = 720
    $win.MinWidth = 720
    $win.MinHeight = 480
    $win.Background = $brush.ConvertFromString("#020617")
    $win.WindowStartupLocation = "CenterOwner"
    if ($Window) { $win.Owner = $Window }
    if (Get-Command Set-SnifferOpsWindowIcon -ErrorAction SilentlyContinue) {
        Set-SnifferOpsWindowIcon -TargetWindow $win
    }

    $root = New-Object System.Windows.Controls.Grid
    $rowTop = New-Object System.Windows.Controls.RowDefinition; $rowTop.Height = "Auto"
    $rowMap = New-Object System.Windows.Controls.RowDefinition; $rowMap.Height = [System.Windows.GridLength]::new(1, [System.Windows.GridUnitType]::Star)
    $rowBottom = New-Object System.Windows.Controls.RowDefinition; $rowBottom.Height = "Auto"
    [void]$root.RowDefinitions.Add($rowTop)
    [void]$root.RowDefinitions.Add($rowMap)
    [void]$root.RowDefinitions.Add($rowBottom)
    $win.Content = $root

    $topBar = New-Object System.Windows.Controls.DockPanel
    $topBar.Margin = "12,10,12,8"
    $topBar.LastChildFill = $true
    [System.Windows.Controls.Grid]::SetRow($topBar, 0)
    [void]$root.Children.Add($topBar)

    $title = New-Object System.Windows.Controls.TextBlock
    $title.Text = "OFFLINE AWARENESS MAP"
    $title.Foreground = $brush.ConvertFromString("#22D3EE")
    $title.FontFamily = "Consolas"
    $title.FontSize = 18
    $title.FontWeight = "Bold"
    $title.VerticalAlignment = "Center"
    [System.Windows.Controls.DockPanel]::SetDock($title, "Left")
    [void]$topBar.Children.Add($title)

    $fitButton = New-Object System.Windows.Controls.Button
    $fitButton.Content = "FIT VIEW"
    $fitButton.Padding = "12,6"
    $fitButton.Margin = "12,0,0,0"
    $fitButton.FontFamily = "Consolas"
    $fitButton.FontWeight = "Bold"
    $fitButton.Background = $brush.ConvertFromString("#111827")
    $fitButton.Foreground = $brush.ConvertFromString("#E5E7EB")
    $fitButton.BorderBrush = $brush.ConvertFromString("#255866")
    [System.Windows.Controls.DockPanel]::SetDock($fitButton, "Right")
    [void]$topBar.Children.Add($fitButton)

    $refreshButton = New-Object System.Windows.Controls.Button
    $refreshButton.Content = "REFRESH"
    $refreshButton.Padding = "12,6"
    $refreshButton.Margin = "12,0,0,0"
    $refreshButton.FontFamily = "Consolas"
    $refreshButton.FontWeight = "Bold"
    $refreshButton.Background = $brush.ConvertFromString("#111827")
    $refreshButton.Foreground = $brush.ConvertFromString("#E5E7EB")
    $refreshButton.BorderBrush = $brush.ConvertFromString("#21F982")
    [System.Windows.Controls.DockPanel]::SetDock($refreshButton, "Right")
    [void]$topBar.Children.Add($refreshButton)

    $statusText = New-Object System.Windows.Controls.TextBlock
    $statusText.Text = "Loading awareness data..."
    $statusText.Foreground = $brush.ConvertFromString("#9CA3AF")
    $statusText.FontFamily = "Consolas"
    $statusText.FontSize = 12
    $statusText.VerticalAlignment = "Center"
    $statusText.Margin = "16,0,0,0"
    $statusText.TextTrimming = "CharacterEllipsis"
    [void]$topBar.Children.Add($statusText)

    $mapBorder = New-Object System.Windows.Controls.Border
    $mapBorder.Margin = "12,0,12,0"
    $mapBorder.BorderBrush = $brush.ConvertFromString("#255866")
    $mapBorder.BorderThickness = "1"
    $mapBorder.CornerRadius = "6"
    $mapBorder.Background = $brush.ConvertFromString("#0B1120")
    [System.Windows.Controls.Grid]::SetRow($mapBorder, 1)
    [void]$root.Children.Add($mapBorder)

    $canvas = New-Object System.Windows.Controls.Canvas
    $canvas.ClipToBounds = $true
    $canvas.Background = $brush.ConvertFromString("#0B1120")
    $mapBorder.Child = $canvas

    $legend = New-Object System.Windows.Controls.TextBlock
    $legend.Margin = "12,6,12,10"
    $legend.FontFamily = "Consolas"
    $legend.FontSize = 11
    $legend.TextWrapping = "Wrap"
    $legend.Foreground = $brush.ConvertFromString("#9CA3AF")
    $legend.Text = "WIFI green / BT blue / CELL amber / SDR purple   |   solid = phone GPS, dashed = inferred from co-seen GPS, hollow = node usual area   |   drag to pan, wheel to zoom, click a dot for details. Map tiles download once when online and are cached for offline use."
    [System.Windows.Controls.Grid]::SetRow($legend, 2)
    [void]$root.Children.Add($legend)

    # Shared mutable view state (hashtable => shared by reference between the
    # closures below).
    $view = @{
        CenterLat = 0.0
        CenterLon = 0.0
        Zoom = 16.0
        HasFit = $false
        Placements = @()
        DragStart = $null
        DragOriginWorld = $null
        Panning = $false
        OfflineUntil = [datetime]::MinValue
        TileStatus = ""
    }

    $fitView = {
        $located = @($view.Placements | Where-Object { $null -ne $_.Latitude -and $null -ne $_.Longitude })
        if ($located.Count -eq 0) { return }
        $minLat = ($located | Measure-Object -Property Latitude -Minimum).Minimum
        $maxLat = ($located | Measure-Object -Property Latitude -Maximum).Maximum
        $minLon = ($located | Measure-Object -Property Longitude -Minimum).Minimum
        $maxLon = ($located | Measure-Object -Property Longitude -Maximum).Maximum
        $view.CenterLat = ($minLat + $maxLat) / 2.0
        $view.CenterLon = ($minLon + $maxLon) / 2.0
        # World-pixel span at zoom 0, then pick the zoom that fits the canvas.
        $pxMin = Get-OfflineMapWorldPixel -Lat $maxLat -Lon $minLon -Zoom 0.0
        $pxMax = Get-OfflineMapWorldPixel -Lat $minLat -Lon $maxLon -Zoom 0.0
        $dx = [Math]::Max(0.0000001, [Math]::Abs($pxMax[0] - $pxMin[0]))
        $dy = [Math]::Max(0.0000001, [Math]::Abs($pxMax[1] - $pxMin[1]))
        $w = [Math]::Max(200.0, $canvas.ActualWidth - 100)
        $h = [Math]::Max(150.0, $canvas.ActualHeight - 100)
        $zoom = [Math]::Min([Math]::Log($w / $dx, 2.0), [Math]::Log($h / $dy, 2.0))
        $view.Zoom = [Math]::Max(3.0, [Math]::Min(18.0, $zoom))
        $view.HasFit = $true
    }.GetNewClosure()

    $project = {
        param([double] $Lat, [double] $Lon)
        $center = Get-OfflineMapWorldPixel -Lat $view.CenterLat -Lon $view.CenterLon -Zoom $view.Zoom
        $world = Get-OfflineMapWorldPixel -Lat $Lat -Lon $Lon -Zoom $view.Zoom
        return @(
            ($world[0] - $center[0] + $canvas.ActualWidth / 2.0),
            ($world[1] - $center[1] + $canvas.ActualHeight / 2.0)
        )
    }.GetNewClosure()

    $drawTiles = {
        # Draws cached tiles; downloads missing ones (capped per pass) unless
        # panning or in offline backoff. Returns @(drawnCount, missingCount).
        $w = $canvas.ActualWidth
        $h = $canvas.ActualHeight
        $tileZ = [int][Math]::Max(2, [Math]::Min(19, [Math]::Round($view.Zoom)))
        $scale = [Math]::Pow(2.0, $view.Zoom - $tileZ)
        $tileSize = 256.0 * $scale
        $center = Get-OfflineMapWorldPixel -Lat $view.CenterLat -Lon $view.CenterLon -Zoom $view.Zoom
        $maxTile = [int]([Math]::Pow(2, $tileZ)) - 1
        $txMin = [Math]::Max(0, [int][Math]::Floor(($center[0] - $w / 2.0) / $tileSize))
        $txMax = [Math]::Min($maxTile, [int][Math]::Floor(($center[0] + $w / 2.0) / $tileSize))
        $tyMin = [Math]::Max(0, [int][Math]::Floor(($center[1] - $h / 2.0) / $tileSize))
        $tyMax = [Math]::Min($maxTile, [int][Math]::Floor(($center[1] + $h / 2.0) / $tileSize))

        # Fetch a capped batch of missing tiles first (skip while panning so
        # dragging stays smooth; back off for a while after a failure).
        $canFetch = (-not $view.Panning) -and ((Get-Date) -ge $view.OfflineUntil)
        $fetched = 0
        if ($canFetch) {
            for ($ty = $tyMin; $ty -le $tyMax -and $fetched -lt 12; $ty++) {
                for ($tx = $txMin; $tx -le $txMax -and $fetched -lt 12; $tx++) {
                    $path = Get-OfflineMapTilePath -Z $tileZ -X $tx -Y $ty
                    if (Test-Path -LiteralPath $path) { continue }
                    if (Request-OfflineMapTile -Z $tileZ -X $tx -Y $ty) {
                        $fetched++
                    } else {
                        $view.OfflineUntil = (Get-Date).AddSeconds(90)
                        $ty = $tyMax + 1
                        break
                    }
                }
            }
        }

        $drawn = 0
        $missing = 0
        for ($ty = $tyMin; $ty -le $tyMax; $ty++) {
            for ($tx = $txMin; $tx -le $txMax; $tx++) {
                $path = Get-OfflineMapTilePath -Z $tileZ -X $tx -Y $ty
                if (-not (Test-Path -LiteralPath $path)) { $missing++; continue }
                try {
                    $bmp = New-Object System.Windows.Media.Imaging.BitmapImage
                    $bmp.BeginInit()
                    $bmp.UriSource = New-Object System.Uri($path)
                    $bmp.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
                    $bmp.EndInit()
                    $bmp.Freeze()
                    $img = New-Object System.Windows.Controls.Image
                    $img.Source = $bmp
                    $img.Width = $tileSize + 0.7    # tiny overlap hides seams
                    $img.Height = $tileSize + 0.7
                    $img.Stretch = "Fill"
                    $img.IsHitTestVisible = $false
                    [System.Windows.Media.RenderOptions]::SetBitmapScalingMode($img, [System.Windows.Media.BitmapScalingMode]::HighQuality)
                    [System.Windows.Controls.Canvas]::SetLeft($img, $tx * $tileSize - $center[0] + $w / 2.0)
                    [System.Windows.Controls.Canvas]::SetTop($img, $ty * $tileSize - $center[1] + $h / 2.0)
                    [void]$canvas.Children.Add($img)
                    $drawn++
                } catch {
                    $missing++
                }
            }
        }
        return @($drawn, $missing)
    }.GetNewClosure()

    $drawGrid = {
        # Fallback when no tiles are cached for this view: plain lat/lon grid.
        $w = $canvas.ActualWidth
        $h = $canvas.ActualHeight
        $mpp = Get-OfflineMapMetersPerPixel -Lat $view.CenterLat -Zoom $view.Zoom
        $kLat = 111320.0
        $step = 5.0
        foreach ($candidate in @(0.00005, 0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0)) {
            if (($candidate * $kLat / $mpp) -ge 70) { $step = $candidate; break }
        }
        $latSpan = $h * $mpp / $kLat
        $lonSpan = $w * $mpp / ($kLat * [Math]::Max(0.05, [Math]::Cos($view.CenterLat * [Math]::PI / 180.0)))
        $latStart = [Math]::Floor(($view.CenterLat - $latSpan) / $step) * $step
        $lonStart = [Math]::Floor(($view.CenterLon - $lonSpan) / $step) * $step
        for ($lat = $latStart; $lat -le $view.CenterLat + $latSpan; $lat += $step) {
            $pt = & $project $lat $view.CenterLon
            if ($pt[1] -lt -10 -or $pt[1] -gt $h + 10) { continue }
            $line = New-Object System.Windows.Shapes.Line
            $line.X1 = 0; $line.X2 = $w; $line.Y1 = $pt[1]; $line.Y2 = $pt[1]
            $line.Stroke = $brush.ConvertFromString("#143B46")
            $line.StrokeThickness = 1
            $line.IsHitTestVisible = $false
            [void]$canvas.Children.Add($line)
            $label = New-Object System.Windows.Controls.TextBlock
            $label.Text = "{0:N4}" -f $lat
            $label.Foreground = $brush.ConvertFromString("#2E5560")
            $label.FontFamily = "Consolas"
            $label.FontSize = 10
            $label.IsHitTestVisible = $false
            [System.Windows.Controls.Canvas]::SetLeft($label, 4)
            [System.Windows.Controls.Canvas]::SetTop($label, $pt[1] + 2)
            [void]$canvas.Children.Add($label)
        }
        for ($lon = $lonStart; $lon -le $view.CenterLon + $lonSpan; $lon += $step) {
            $pt = & $project $view.CenterLat $lon
            if ($pt[0] -lt -10 -or $pt[0] -gt $w + 10) { continue }
            $line = New-Object System.Windows.Shapes.Line
            $line.X1 = $pt[0]; $line.X2 = $pt[0]; $line.Y1 = 0; $line.Y2 = $h
            $line.Stroke = $brush.ConvertFromString("#143B46")
            $line.StrokeThickness = 1
            $line.IsHitTestVisible = $false
            [void]$canvas.Children.Add($line)
            $label = New-Object System.Windows.Controls.TextBlock
            $label.Text = "{0:N4}" -f $lon
            $label.Foreground = $brush.ConvertFromString("#2E5560")
            $label.FontFamily = "Consolas"
            $label.FontSize = 10
            $label.IsHitTestVisible = $false
            [System.Windows.Controls.Canvas]::SetLeft($label, $pt[0] + 3)
            [System.Windows.Controls.Canvas]::SetTop($label, $h - 16)
            [void]$canvas.Children.Add($label)
        }
    }.GetNewClosure()

    $redraw = {
        $canvas.Children.Clear()
        $w = $canvas.ActualWidth
        $h = $canvas.ActualHeight
        if ($w -lt 40 -or $h -lt 40) { return }

        $located = @($view.Placements | Where-Object { $null -ne $_.Latitude -and $null -ne $_.Longitude })
        if ($located.Count -eq 0) {
            $msg = New-Object System.Windows.Controls.TextBlock
            $msg.Text = "No placeable signals yet.`nSync the phone with GPS enabled to seed the map."
            $msg.Foreground = $brush.ConvertFromString("#637082")
            $msg.FontFamily = "Consolas"
            $msg.FontSize = 14
            [System.Windows.Controls.Canvas]::SetLeft($msg, 24)
            [System.Windows.Controls.Canvas]::SetTop($msg, 24)
            [void]$canvas.Children.Add($msg)
            return
        }
        if (-not $view.HasFit) { & $fitView }

        # Map background: cached tiles, or the plain grid if none exist here.
        $tileResult = & $drawTiles
        $tilesDrawn = $tileResult[0]
        $tilesMissing = $tileResult[1]
        if ($tilesDrawn -eq 0) { & $drawGrid }
        $view.TileStatus = if ($tilesMissing -eq 0 -and $tilesDrawn -gt 0) {
            "tiles cached"
        } elseif ((Get-Date) -lt $view.OfflineUntil) {
            "tiles: $tilesMissing missing (offline - showing cache)"
        } elseif ($tilesMissing -gt 0) {
            "tiles: downloading $tilesMissing more"
        } else {
            "no tiles cached for this area yet"
        }

        # Spread markers that land in the same pixel cell into a small fan so
        # co-located signals stay individually clickable.
        $clusters = [ordered]@{}
        foreach ($placement in $located) {
            $pt = & $project $placement.Latitude $placement.Longitude
            if ($pt[0] -lt -30 -or $pt[0] -gt $w + 30 -or $pt[1] -lt -30 -or $pt[1] -gt $h + 30) { continue }
            $clusterKey = "$([Math]::Round($pt[0] / 14)),$([Math]::Round($pt[1] / 14))"
            if (-not $clusters.Contains($clusterKey)) { $clusters[$clusterKey] = New-Object System.Collections.ArrayList }
            [void]$clusters[$clusterKey].Add(@{ Placement = $placement; X = $pt[0]; Y = $pt[1] })
        }

        foreach ($clusterKey in $clusters.Keys) {
            $cluster = $clusters[$clusterKey]
            $index = 0
            foreach ($entry in $cluster) {
                $x = $entry.X
                $y = $entry.Y
                if ($cluster.Count -gt 1 -and $index -gt 0) {
                    $angle = 2.39996 * $index   # golden angle keeps the fan even
                    $spreadRadius = 7.0 + 3.0 * [Math]::Sqrt($index)
                    $x += $spreadRadius * [Math]::Cos($angle)
                    $y += $spreadRadius * [Math]::Sin($angle)
                }
                $placement = $entry.Placement
                $color = Get-OfflineMapTypeColor -Type $placement.Type
                if ($placement.Class -in @("Alert", "Watch")) {
                    $ring = New-Object System.Windows.Shapes.Ellipse
                    $ring.Width = 19
                    $ring.Height = 19
                    $ring.Stroke = $brush.ConvertFromString($(if ($placement.Class -eq "Alert") { "#EF4444" } else { "#F59E0B" }))
                    $ring.StrokeThickness = 1.4
                    $ring.IsHitTestVisible = $false
                    [System.Windows.Controls.Canvas]::SetLeft($ring, $x - 9.5)
                    [System.Windows.Controls.Canvas]::SetTop($ring, $y - 9.5)
                    [void]$canvas.Children.Add($ring)
                }
                $dot = New-Object System.Windows.Shapes.Ellipse
                $dot.Width = 11
                $dot.Height = 11
                switch ($placement.PlacementTier) {
                    "gps" {
                        $dot.Fill = $brush.ConvertFromString($color)
                        $dot.Stroke = $brush.ConvertFromString("#0B1120")
                        $dot.StrokeThickness = 1.2
                    }
                    "linked" {
                        $dot.Fill = $brush.ConvertFromString($color)
                        $dot.Stroke = $brush.ConvertFromString($color)
                        $dot.StrokeThickness = 1.6
                        $dot.StrokeDashArray = [System.Windows.Media.DoubleCollection]::Parse("2,2")
                        $dot.Opacity = 0.85
                    }
                    default {
                        $dot.Fill = $brush.ConvertFromString("#660B1120")
                        $dot.Stroke = $brush.ConvertFromString($color)
                        $dot.StrokeThickness = 1.6
                        $dot.StrokeDashArray = [System.Windows.Media.DoubleCollection]::Parse("2,2")
                    }
                }
                $tierLabel = switch ($placement.PlacementTier) {
                    "gps" { "GPS" }
                    "linked" { "INFERRED (co-seen GPS)" }
                    default { "INFERRED (node area)" }
                }
                $dot.ToolTip = "$($placement.Name)`n$($placement.Type) / $($placement.SpecificType)`n$tierLabel`n$($placement.PlacementNote)`nSeen $($placement.SeenCount)x, last $($placement.LastSeen)"
                $dot.Tag = $placement
                $dot.Cursor = "Hand"
                $dot.Add_MouseLeftButtonUp({
                    param($sender, $eventArgs)
                    $eventArgs.Handled = $true
                    $item = $sender.Tag
                    if (Get-Command Show-SignalDetailWindow -ErrorAction SilentlyContinue) {
                        Show-SignalDetailWindow -Title "Offline Map Signal" -Accent (Get-OfflineMapTypeColor -Type $item.Type) -Item ([pscustomobject][ordered]@{
                            Name = $item.Name
                            Type = $item.Type
                            Classification = $item.SpecificType
                            Class = $item.Class
                            Placement = $item.PlacementTier
                            PlacementNote = $item.PlacementNote
                            Latitude = "{0:N6}" -f $item.Latitude
                            Longitude = "{0:N6}" -f $item.Longitude
                            SeenCount = $item.SeenCount
                            LastSignal = $item.LastSignal
                            LastSeen = $item.LastSeen
                            Nodes = (@($item.NodeIds) -join ", ")
                        })
                    }
                })
                [System.Windows.Controls.Canvas]::SetLeft($dot, $x - 5.5)
                [System.Windows.Controls.Canvas]::SetTop($dot, $y - 5.5)
                [void]$canvas.Children.Add($dot)
                $index++
            }
        }

        # Scale bar: a round meter length close to a fifth of the width, on a
        # translucent backing so it stays readable over tiles.
        $mpp = Get-OfflineMapMetersPerPixel -Lat $view.CenterLat -Zoom $view.Zoom
        $targetMeters = $w * $mpp / 5.0
        $magnitude = [Math]::Pow(10, [Math]::Floor([Math]::Log10([Math]::Max(1.0, $targetMeters))))
        $barMeters = $magnitude
        foreach ($mult in @(1, 2, 5)) {
            if ($mult * $magnitude -le $targetMeters) { $barMeters = $mult * $magnitude }
        }
        $barPx = $barMeters / $mpp
        $barBack = New-Object System.Windows.Shapes.Rectangle
        $barBack.Width = $barPx + 16
        $barBack.Height = 34
        $barBack.Fill = $brush.ConvertFromString("#B0020617")
        $barBack.RadiusX = 4; $barBack.RadiusY = 4
        $barBack.IsHitTestVisible = $false
        [System.Windows.Controls.Canvas]::SetLeft($barBack, 10)
        [System.Windows.Controls.Canvas]::SetTop($barBack, $h - 46)
        [void]$canvas.Children.Add($barBack)
        $bar = New-Object System.Windows.Shapes.Line
        $bar.X1 = 18; $bar.X2 = 18 + $barPx; $bar.Y1 = $h - 20; $bar.Y2 = $h - 20
        $bar.Stroke = $brush.ConvertFromString("#E5E7EB")
        $bar.StrokeThickness = 2
        $bar.IsHitTestVisible = $false
        [void]$canvas.Children.Add($bar)
        $barText = New-Object System.Windows.Controls.TextBlock
        $barText.Text = $(if ($barMeters -ge 1000) { "{0:N0} km" -f ($barMeters / 1000) } else { "{0:N0} m" -f $barMeters })
        $barText.Foreground = $brush.ConvertFromString("#E5E7EB")
        $barText.FontFamily = "Consolas"
        $barText.FontSize = 11
        $barText.IsHitTestVisible = $false
        [System.Windows.Controls.Canvas]::SetLeft($barText, 20)
        [System.Windows.Controls.Canvas]::SetTop($barText, $h - 40)
        [void]$canvas.Children.Add($barText)

        $attribution = New-Object System.Windows.Controls.TextBlock
        $attribution.Text = $(if ($tilesDrawn -gt 0) { $attributionText } else { "OFFLINE GRID - no cached tiles for this area" })
        $attribution.Foreground = $brush.ConvertFromString("#8390A1")
        $attribution.Background = $brush.ConvertFromString("#B0020617")
        $attribution.Padding = "4,1,4,1"
        $attribution.FontFamily = "Consolas"
        $attribution.FontSize = 10
        $attribution.IsHitTestVisible = $false
        $attribution.Add_Loaded({ param($sender, $e)
            [System.Windows.Controls.Canvas]::SetLeft($sender, $sender.Parent.ActualWidth - $sender.ActualWidth - 8)
        })
        [System.Windows.Controls.Canvas]::SetLeft($attribution, [Math]::Max(8, $w - 420))
        [System.Windows.Controls.Canvas]::SetTop($attribution, $h - 18)
        [void]$canvas.Children.Add($attribution)
    }.GetNewClosure()

    $refresh = {
        $view.Placements = @(Get-OfflineMapPlacements -Profiles @(Get-AwarenessProfiles))
        $gps = @($view.Placements | Where-Object { $_.PlacementTier -eq "gps" }).Count
        $linked = @($view.Placements | Where-Object { $_.PlacementTier -eq "linked" }).Count
        $anchored = @($view.Placements | Where-Object { $_.PlacementTier -eq "anchor" }).Count
        $unplaced = @($view.Placements | Where-Object { $_.PlacementTier -eq "unplaced" }).Count
        & $redraw
        $tileNote = if ($view.TileStatus) { " | $($view.TileStatus)" } else { "" }
        $statusText.Text = "$gps GPS / $linked co-seen / $anchored node-area / $unplaced unplaced$tileNote - $(Get-Date -Format 'HH:mm:ss')"
    }.GetNewClosure()

    $refreshButton.Add_Click({
        Invoke-AppAction -Context "Refresh offline map" -Action {
            $view.OfflineUntil = [datetime]::MinValue   # manual refresh retries downloads
            & $refresh
        }
    }.GetNewClosure())
    $fitButton.Add_Click({
        Invoke-AppAction -Context "Fit offline map" -Action { & $fitView; & $refresh }
    }.GetNewClosure())

    $canvas.Add_SizeChanged({ & $redraw }.GetNewClosure())
    $canvas.Add_MouseWheel({
        param($sender, $eventArgs)
        $zoomStep = $(if ($eventArgs.Delta -gt 0) { 0.5 } else { -0.5 })
        $newZoom = [Math]::Max(3.0, [Math]::Min(19.0, $view.Zoom + $zoomStep))
        if ($newZoom -eq $view.Zoom) { return }
        # Keep the geographic point under the cursor fixed while zooming.
        $pos = $eventArgs.GetPosition($canvas)
        $center = Get-OfflineMapWorldPixel -Lat $view.CenterLat -Lon $view.CenterLon -Zoom $view.Zoom
        $cursorWorldX = $center[0] + ($pos.X - $canvas.ActualWidth / 2.0)
        $cursorWorldY = $center[1] + ($pos.Y - $canvas.ActualHeight / 2.0)
        $factor = [Math]::Pow(2.0, $newZoom - $view.Zoom)
        $newCenterX = $cursorWorldX * $factor - ($pos.X - $canvas.ActualWidth / 2.0)
        $newCenterY = $cursorWorldY * $factor - ($pos.Y - $canvas.ActualHeight / 2.0)
        $latLon = Get-OfflineMapLatLon -X $newCenterX -Y $newCenterY -Zoom $newZoom
        $view.Zoom = $newZoom
        $view.CenterLat = $latLon[0]
        $view.CenterLon = $latLon[1]
        & $redraw
    }.GetNewClosure())
    # Pan starts only after a small movement threshold so single clicks still
    # reach the signal dots underneath.
    $canvas.Add_MouseLeftButtonDown({
        param($sender, $eventArgs)
        $view.DragStart = $eventArgs.GetPosition($canvas)
        $view.DragOriginWorld = Get-OfflineMapWorldPixel -Lat $view.CenterLat -Lon $view.CenterLon -Zoom $view.Zoom
        $view.Panning = $false
    }.GetNewClosure())
    $canvas.Add_MouseMove({
        param($sender, $eventArgs)
        if ($null -eq $view.DragStart) { return }
        if ($eventArgs.LeftButton -ne [System.Windows.Input.MouseButtonState]::Pressed) { return }
        $pos = $eventArgs.GetPosition($canvas)
        $dx = $pos.X - $view.DragStart.X
        $dy = $pos.Y - $view.DragStart.Y
        if (-not $view.Panning) {
            if (([Math]::Abs($dx) + [Math]::Abs($dy)) -lt 4) { return }
            $view.Panning = $true
            [void]$canvas.CaptureMouse()
        }
        $latLon = Get-OfflineMapLatLon -X ($view.DragOriginWorld[0] - $dx) -Y ($view.DragOriginWorld[1] - $dy) -Zoom $view.Zoom
        $view.CenterLat = $latLon[0]
        $view.CenterLon = $latLon[1]
        & $redraw
    }.GetNewClosure())
    $canvas.Add_PreviewMouseLeftButtonUp({
        $wasPanning = $view.Panning
        $view.DragStart = $null
        $view.Panning = $false
        if ($canvas.IsMouseCaptured) { $canvas.ReleaseMouseCapture() }
        if ($wasPanning) { & $redraw }   # fetch pass for newly exposed tiles
    }.GetNewClosure())

    $timer = New-Object Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromSeconds(10)
    $timer.Add_Tick({
        Invoke-AppAction -Context "Offline map auto refresh" -Action { & $refresh }
    }.GetNewClosure())

    $win.Add_Loaded({
        Invoke-AppAction -Context "Load offline map" -Action {
            & $refresh
            & $fitView
            & $refresh
            $timer.Start()
        }
    }.GetNewClosure())
    $win.Add_Closed({ $timer.Stop() }.GetNewClosure())

    if (Get-Command Apply-SnifferOpsFont -ErrorAction SilentlyContinue) {
        Apply-SnifferOpsFont -Root $win
    }
    $script:OfflineMapWindow = $win
    [void]$win.Show()
}
