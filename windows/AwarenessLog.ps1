# Durable signal awareness log and LAN sync endpoint for mobile sensor nodes.

$script:AwarenessLogPath = $null
$script:AwarenessSyncListener = $null
$script:AwarenessSyncAsyncResult = $null

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

    $frequency = ConvertTo-AwarenessNumber $Signal.frequencyHz
    if ($type.ToUpperInvariant() -eq "RTL_SDR" -and $null -ne $frequency) {
        $bucketHz = 250000.0
        $id = [string]([long]([Math]::Round($frequency / $bucketHz) * $bucketHz))
        return "$($type.ToUpperInvariant())|$id"
    }

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
    $text = ([string]$Value).Trim().TrimEnd("%")
    $number = 0.0
    if ([double]::TryParse($text, [ref]$number)) { return $number }
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
        $signalStrength = $signal.signalStrength
        $signalStrengthNumber = ConvertTo-AwarenessNumber $signalStrength
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
                StrongestSignalNumeric = $signalStrengthNumber
                LastSignal = $signal.signalStrength
                LastSignalNumeric = $signalStrengthNumber
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
        $existing.LastSignalNumeric = $signalStrengthNumber
        $strongestNumber = ConvertTo-AwarenessNumber $existing.StrongestSignalNumeric
        if ($null -ne $signalStrengthNumber -and ($null -eq $strongestNumber -or $signalStrengthNumber -gt $strongestNumber)) {
            $existing.StrongestSignal = $signal.signalStrength
            $existing.StrongestSignalNumeric = $signalStrengthNumber
        } elseif ($null -eq $existing.StrongestSignal -or [string]::IsNullOrWhiteSpace([string]$existing.StrongestSignal)) {
            $existing.StrongestSignal = $signal.signalStrength
            $existing.StrongestSignalNumeric = $signalStrengthNumber
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
            SignalStrengthNumeric = $signalStrengthNumber
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

function Start-AwarenessSyncServer {
    param(
        [string] $BindAddress = "0.0.0.0",
        [int] $Port = 8765,
        [string] $LogPath
    )

    if ($script:AwarenessSyncListener) { return }

    $ip = if ($BindAddress -eq "0.0.0.0") {
        [System.Net.IPAddress]::Any
    } else {
        [System.Net.IPAddress]::Parse($BindAddress)
    }
    $listener = New-Object System.Net.Sockets.TcpListener($ip, $Port)
    $listener.Start()
    $script:AwarenessSyncListener = $listener
    $script:AwarenessSyncAsyncResult = $listener.BeginAcceptTcpClient($null, $null)
}

function Stop-AwarenessSyncServer {
    try {
        if ($script:AwarenessSyncListener) {
            $script:AwarenessSyncListener.Stop()
        }
    } catch {}
    $script:AwarenessSyncListener = $null
    $script:AwarenessSyncAsyncResult = $null
}

function Receive-AwarenessSyncRequests {
    param([string] $LogPath)

    if (-not $script:AwarenessSyncListener) { return 0 }
    $handled = 0
    if (-not $script:AwarenessSyncAsyncResult) {
        $script:AwarenessSyncAsyncResult = $script:AwarenessSyncListener.BeginAcceptTcpClient($null, $null)
    }
    while ($script:AwarenessSyncAsyncResult -and $script:AwarenessSyncAsyncResult.IsCompleted) {
        $client = $null
        try {
            $client = $script:AwarenessSyncListener.EndAcceptTcpClient($script:AwarenessSyncAsyncResult)
            $script:AwarenessSyncAsyncResult = $script:AwarenessSyncListener.BeginAcceptTcpClient($null, $null)
            $request = Read-AwarenessHttpRequest -Client $client
            $path = $request.Path.ToLowerInvariant()
            if ($request.Method -eq "GET" -and $path -eq "/snifferops/health") {
                Send-AwarenessTcpJsonResponse -Client $client -Body @{ ok = $true; service = "snifferops-awareness" }
                $handled++
                continue
            }
            if ($request.Method -eq "GET" -and $path -eq "/snifferops/awareness") {
                Send-AwarenessTcpJsonResponse -Client $client -Body (Get-AwarenessSyncPayload)
                $handled++
                continue
            }
            if ($request.Method -eq "POST" -and $path -eq "/snifferops/sync") {
                $snapshot = $request.Body | ConvertFrom-Json
                $merge = Merge-AwarenessSnapshot -Snapshot $snapshot
                $payload = Get-AwarenessSyncPayload
                $payload["merged"] = $merge.Merged
                Send-AwarenessTcpJsonResponse -Client $client -Body $payload
                $handled++
                continue
            }
            Send-AwarenessTcpJsonResponse -Client $client -StatusCode 404 -Body @{ error = "not found" }
            $handled++
        } catch {
            try {
                if ($LogPath) {
                    Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Awareness sync error: $($_.Exception.Message)" -ErrorAction SilentlyContinue
                }
                if ($client -and $client.Connected) {
                    Send-AwarenessTcpJsonResponse -Client $client -StatusCode 500 -Body @{ error = $_.Exception.Message }
                }
            } catch {}
        } finally {
            try { if ($client) { $client.Close() } } catch {}
        }
    }
    return $handled
}

function Read-AwarenessHttpRequest {
    param([System.Net.Sockets.TcpClient] $Client)

    $stream = $Client.GetStream()
    $buffer = New-Object byte[] 65536
    $bytes = New-Object System.Collections.Generic.List[byte]
    $contentLength = 0
    $headerText = $null

    while ($true) {
        $read = $stream.Read($buffer, 0, $buffer.Length)
        if ($read -le 0) { break }
        for ($i = 0; $i -lt $read; $i++) { $bytes.Add($buffer[$i]) | Out-Null }
        $text = [System.Text.Encoding]::UTF8.GetString($bytes.ToArray())
        $headerEnd = $text.IndexOf("`r`n`r`n")
        if ($headerEnd -ge 0) {
            $headerText = $text.Substring(0, $headerEnd)
            foreach ($line in $headerText -split "`r`n") {
                if ($line -match '^Content-Length:\s*(\d+)') { $contentLength = [int]$Matches[1] }
            }
            $bodyBytesAlready = $bytes.Count - ($headerEnd + 4)
            if ($bodyBytesAlready -ge $contentLength) { break }
        }
    }

    if (-not $headerText) { throw "Invalid HTTP request" }
    $allText = [System.Text.Encoding]::UTF8.GetString($bytes.ToArray())
    $headerEnd = $allText.IndexOf("`r`n`r`n")
    $body = if ($contentLength -gt 0) { $allText.Substring($headerEnd + 4, $contentLength) } else { "" }
    $firstLine = ($headerText -split "`r`n")[0]
    $parts = $firstLine -split "\s+"
    return [pscustomobject]@{
        Method = if ($parts.Count -gt 0) { $parts[0].ToUpperInvariant() } else { "" }
        Path = if ($parts.Count -gt 1) { $parts[1] } else { "/" }
        Body = $body
    }
}

function Send-AwarenessTcpJsonResponse {
    param(
        [System.Net.Sockets.TcpClient] $Client,
        [object] $Body,
        [int] $StatusCode = 200
    )

    $reason = switch ($StatusCode) {
        200 { "OK" }
        404 { "Not Found" }
        500 { "Internal Server Error" }
        default { "OK" }
    }
    $json = $Body | ConvertTo-Json -Depth 40
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $header = "HTTP/1.1 $StatusCode $reason`r`nContent-Type: application/json`r`nContent-Length: $($bodyBytes.Length)`r`nConnection: close`r`n`r`n"
    $headerBytes = [System.Text.Encoding]::ASCII.GetBytes($header)
    $stream = $Client.GetStream()
    $stream.Write($headerBytes, 0, $headerBytes.Length)
    $stream.Write($bodyBytes, 0, $bodyBytes.Length)
    $stream.Flush()
}
