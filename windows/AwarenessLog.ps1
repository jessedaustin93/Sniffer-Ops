# Durable signal awareness log and LAN sync endpoint for mobile sensor nodes.

$script:AwarenessLogPath = $null
$script:AwarenessSyncListener = $null
$script:AwarenessSyncAsyncResult = $null
$script:AwarenessSyncStop = $false

function Initialize-AwarenessLog {
    param([string] $Path)

    $script:AwarenessLogPath = $Path
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        Save-AwarenessState -State ([ordered]@{
            Schema = 1
            CreatedAt = (Get-Date).ToUniversalTime().ToString("o")
            UpdatedAt = (Get-Date).ToUniversalTime().ToString("o")
            Signals = @{}
        })
    }
}

function Read-AwarenessState {
    if (-not $script:AwarenessLogPath) { throw "Awareness log is not initialized." }
    if (-not (Test-Path -LiteralPath $script:AwarenessLogPath)) {
        Initialize-AwarenessLog -Path $script:AwarenessLogPath
    }

    $raw = Get-Content -LiteralPath $script:AwarenessLogPath -Raw -ErrorAction SilentlyContinue
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return [ordered]@{ Schema = 1; CreatedAt = (Get-Date).ToUniversalTime().ToString("o"); UpdatedAt = (Get-Date).ToUniversalTime().ToString("o"); Signals = @{} }
    }

    $state = $raw | ConvertFrom-Json
    $signals = @{}
    if ($state.Signals) {
        foreach ($property in $state.Signals.PSObject.Properties) {
            $signals[$property.Name] = $property.Value
        }
    }

    return [ordered]@{
        Schema = if ($state.Schema) { [int]$state.Schema } else { 1 }
        CreatedAt = if ($state.CreatedAt) { [string]$state.CreatedAt } else { (Get-Date).ToUniversalTime().ToString("o") }
        UpdatedAt = if ($state.UpdatedAt) { [string]$state.UpdatedAt } else { (Get-Date).ToUniversalTime().ToString("o") }
        Signals = $signals
    }
}

function Save-AwarenessState {
    param([object] $State)

    $State.UpdatedAt = (Get-Date).ToUniversalTime().ToString("o")
    $json = $State | ConvertTo-Json -Depth 40
    $temp = "$script:AwarenessLogPath.tmp"
    Set-Content -LiteralPath $temp -Value $json -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $script:AwarenessLogPath -Force
}

function Get-AwarenessSignalKey {
    param([object] $Signal)

    $type = ([string]$Signal.type).Trim()
    if (-not $type) { $type = ([string]$Signal.signalType).Trim() }
    if (-not $type) { $type = "UNKNOWN" }

    $id = ([string]$Signal.address).Trim()
    if (-not $id) { $id = ([string]$Signal.id).Trim() }
    if (-not $id -and $Signal.frequencyHz) { $id = [string]$Signal.frequencyHz }
    if (-not $id) { $id = ([string]$Signal.name).Trim() }
    if (-not $id) { $id = [guid]::NewGuid().ToString("N") }

    return "$($type.ToUpperInvariant())|$($id.ToUpperInvariant())"
}

function ConvertTo-AwarenessNumber {
    param([object] $Value)
    if ($null -eq $Value) { return $null }
    $number = 0.0
    if ([double]::TryParse(([string]$Value), [ref]$number)) { return $number }
    return $null
}

function Merge-AwarenessSnapshot {
    param([object] $Snapshot)

    $state = Read-AwarenessState
    $now = (Get-Date).ToUniversalTime().ToString("o")
    $nodeId = ([string]$Snapshot.nodeId).Trim()
    if (-not $nodeId) { $nodeId = "unknown-node" }
    $nodeName = ([string]$Snapshot.nodeName).Trim()
    if (-not $nodeName) { $nodeName = $nodeId }
    $nodeLat = ConvertTo-AwarenessNumber $Snapshot.location.latitude
    $nodeLon = ConvertTo-AwarenessNumber $Snapshot.location.longitude
    $nodeAccuracy = ConvertTo-AwarenessNumber $Snapshot.location.accuracyMeters
    $signals = @($Snapshot.signals)
    $merged = 0

    foreach ($signal in $signals) {
        $key = Get-AwarenessSignalKey -Signal $signal
        $signalLat = ConvertTo-AwarenessNumber $signal.latitude
        $signalLon = ConvertTo-AwarenessNumber $signal.longitude
        $signalAccuracy = ConvertTo-AwarenessNumber $signal.accuracyMeters
        if ($null -eq $signalLat) { $signalLat = $nodeLat }
        if ($null -eq $signalLon) { $signalLon = $nodeLon }
        if ($null -eq $signalAccuracy) { $signalAccuracy = $nodeAccuracy }
        $existing = $state.Signals[$key]
        if (-not $existing) {
            $existing = [pscustomobject][ordered]@{
                Key = $key
                Name = [string]$signal.name
                Address = [string]$signal.address
                Type = [string]$signal.type
                SpecificType = [string]$signal.deviceClass
                Manufacturer = [string]$signal.manufacturer
                ThreatLevel = [string]$signal.threatLevel
                Notes = [string]$signal.notes
                Channel = $signal.channel
                FrequencyHz = $signal.frequencyHz
                FirstSeen = $now
                LastSeen = $now
                SeenCount = 0
                StrongestSignal = $signal.signalStrength
                LastSignal = $signal.signalStrength
                NodeIds = @()
                Sightings = @()
                EstimatedLatitude = $null
                EstimatedLongitude = $null
            }
            $state.Signals[$key] = $existing
        }

        $existing.Name = if ([string]$signal.name) { [string]$signal.name } else { $existing.Name }
        $existing.Address = if ([string]$signal.address) { [string]$signal.address } else { $existing.Address }
        $existing.Type = if ([string]$signal.type) { [string]$signal.type } else { $existing.Type }
        $existing.SpecificType = if ([string]$signal.deviceClass) { [string]$signal.deviceClass } else { $existing.SpecificType }
        $existing.Manufacturer = if ([string]$signal.manufacturer) { [string]$signal.manufacturer } else { $existing.Manufacturer }
        $existing.ThreatLevel = if ([string]$signal.threatLevel) { [string]$signal.threatLevel } else { $existing.ThreatLevel }
        $existing.Notes = if ([string]$signal.notes) { [string]$signal.notes } else { $existing.Notes }
        $existing.Channel = if ($signal.channel) { $signal.channel } else { $existing.Channel }
        $existing.FrequencyHz = if ($signal.frequencyHz) { $signal.frequencyHz } else { $existing.FrequencyHz }
        $existing.LastSeen = $now
        $existing.SeenCount = [int]$existing.SeenCount + 1
        $existing.LastSignal = $signal.signalStrength
        if ($null -eq $existing.StrongestSignal -or ([int]$signal.signalStrength -gt [int]$existing.StrongestSignal)) {
            $existing.StrongestSignal = $signal.signalStrength
        }

        $nodes = @($existing.NodeIds)
        if ($nodes -notcontains $nodeId) { $nodes += $nodeId }
        $existing.NodeIds = @($nodes)

        $sightings = @($existing.Sightings)
        $sightings += [pscustomobject][ordered]@{
            At = $now
            NodeId = $nodeId
            NodeName = $nodeName
            Latitude = $signalLat
            Longitude = $signalLon
            AccuracyMeters = $signalAccuracy
            NodeLatitude = $nodeLat
            NodeLongitude = $nodeLon
            SignalStrength = $signal.signalStrength
        }
        if ($sightings.Count -gt 100) {
            $sightings = @($sightings | Select-Object -Last 100)
        }
        $existing.Sightings = @($sightings)

        $geo = @($sightings | Where-Object { $null -ne $_.Latitude -and $null -ne $_.Longitude })
        if ($geo.Count -gt 0) {
            $existing.EstimatedLatitude = ($geo | Measure-Object -Property Latitude -Average).Average
            $existing.EstimatedLongitude = ($geo | Measure-Object -Property Longitude -Average).Average
        }
        $merged++
    }

    Save-AwarenessState -State $state
    return [pscustomobject][ordered]@{
        Merged = $merged
        TotalSignals = $state.Signals.Count
        UpdatedAt = $state.UpdatedAt
    }
}

function Get-AwarenessRows {
    $state = Read-AwarenessState
    return @($state.Signals.GetEnumerator() | ForEach-Object {
        $signal = $_.Value
        [pscustomobject][ordered]@{
            Type = $signal.Type
            Signal = $signal.Name
            AddressOrFrequency = if ($signal.Address) { $signal.Address } else { $signal.FrequencyHz }
            StrengthOrPower = $signal.LastSignal
            Classification = $signal.SpecificType
            Confidence = $signal.ThreatLevel
            Details = "Seen $($signal.SeenCount)x from $(@($signal.NodeIds).Count) node(s); last $($signal.LastSeen)"
        }
    } | Sort-Object -Property LastSeen -Descending)
}

function Get-AwarenessSyncPayload {
    $state = Read-AwarenessState
    $signals = @($state.Signals.GetEnumerator() | ForEach-Object {
        $signal = $_.Value
        [ordered]@{
            key = $signal.Key
            name = $signal.Name
            address = $signal.Address
            type = $signal.Type
            deviceClass = $signal.SpecificType
            manufacturer = $signal.Manufacturer
            threatLevel = $signal.ThreatLevel
            signalStrength = $signal.LastSignal
            strongestSignal = $signal.StrongestSignal
            channel = $signal.Channel
            frequencyHz = $signal.FrequencyHz
            firstSeen = $signal.FirstSeen
            lastSeen = $signal.LastSeen
            seenCount = $signal.SeenCount
            estimatedLatitude = $signal.EstimatedLatitude
            estimatedLongitude = $signal.EstimatedLongitude
            nodeCount = @($signal.NodeIds).Count
        }
    })

    return [ordered]@{
        schema = 1
        updatedAt = $state.UpdatedAt
        totalSignals = $signals.Count
        signals = $signals
    }
}

function Send-AwarenessJsonResponse {
    param(
        [System.Net.HttpListenerContext] $Context,
        [object] $Body,
        [int] $StatusCode = 200
    )

    $json = $Body | ConvertTo-Json -Depth 40
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $Context.Response.StatusCode = $StatusCode
    $Context.Response.ContentType = "application/json"
    $Context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $Context.Response.Close()
}

function Start-AwarenessSyncServer {
    param(
        [string] $BindAddress = "0.0.0.0",
        [int] $Port = 8765,
        [string] $LogPath
    )

    if ($script:AwarenessSyncListener) { return }

    $prefixHost = if ($BindAddress -eq "0.0.0.0") { "+" } else { $BindAddress }
    $prefix = "http://$prefixHost`:$Port/"
    $script:AwarenessSyncStop = $false
    $listener = New-Object System.Net.HttpListener
    $listener.Prefixes.Add($prefix)
    $listener.Start()
    $script:AwarenessSyncListener = $listener
    $script:AwarenessSyncAsyncResult = $listener.BeginGetContext($null, $null)
}

function Stop-AwarenessSyncServer {
    try {
        if ($script:AwarenessSyncListener) {
            $script:AwarenessSyncListener.Stop()
            $script:AwarenessSyncListener.Close()
        }
    } catch {}
    $script:AwarenessSyncListener = $null
    $script:AwarenessSyncAsyncResult = $null
}

function Receive-AwarenessSyncRequests {
    param([string] $LogPath)

    if (-not $script:AwarenessSyncListener -or -not $script:AwarenessSyncListener.IsListening) { return 0 }
    $handled = 0
    if (-not $script:AwarenessSyncAsyncResult) {
        $script:AwarenessSyncAsyncResult = $script:AwarenessSyncListener.BeginGetContext($null, $null)
    }
    while ($script:AwarenessSyncListener.IsListening -and $script:AwarenessSyncAsyncResult.IsCompleted) {
        $context = $null
        try {
            $context = $script:AwarenessSyncListener.EndGetContext($script:AwarenessSyncAsyncResult)
            $script:AwarenessSyncAsyncResult = $script:AwarenessSyncListener.BeginGetContext($null, $null)
            $path = $context.Request.Url.AbsolutePath.ToLowerInvariant()
            if ($context.Request.HttpMethod -eq "GET" -and $path -eq "/snifferops/health") {
                Send-AwarenessJsonResponse -Context $context -Body @{ ok = $true; service = "snifferops-awareness" }
                $handled++
                continue
            }
            if ($context.Request.HttpMethod -eq "GET" -and $path -eq "/snifferops/awareness") {
                Send-AwarenessJsonResponse -Context $context -Body (Get-AwarenessSyncPayload)
                $handled++
                continue
            }
            if ($context.Request.HttpMethod -eq "POST" -and $path -eq "/snifferops/sync") {
                $reader = New-Object System.IO.StreamReader($context.Request.InputStream, $context.Request.ContentEncoding)
                $raw = $reader.ReadToEnd()
                $snapshot = $raw | ConvertFrom-Json
                $merge = Merge-AwarenessSnapshot -Snapshot $snapshot
                $payload = Get-AwarenessSyncPayload
                $payload["merged"] = $merge.Merged
                Send-AwarenessJsonResponse -Context $context -Body $payload
                $handled++
                continue
            }
            Send-AwarenessJsonResponse -Context $context -StatusCode 404 -Body @{ error = "not found" }
            $handled++
        } catch {
            try {
                if ($LogPath) {
                    Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Awareness sync error: $($_.Exception.Message)" -ErrorAction SilentlyContinue
                }
                if ($context -and $context.Response) {
                    Send-AwarenessJsonResponse -Context $context -StatusCode 500 -Body @{ error = $_.Exception.Message }
                }
            } catch {}
        }
    }
    return $handled
}
