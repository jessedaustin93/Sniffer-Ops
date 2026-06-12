# Durable signal awareness log and LAN sync endpoint for mobile sensor nodes.

$script:AwarenessLogPath = $null
$script:AwarenessSyncListener = $null
$script:AwarenessSyncAsyncResult = $null
$script:AwarenessSdrDeepScan = [ordered]@{
    Id = ""
    State = "idle"
    RequestedAt = ""
    StartedAt = ""
    FinishedAt = ""
    Message = "No PC SDR scan has been requested."
    Error = ""
    SdrSignals = @()
}

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

    if ($type.ToUpperInvariant() -eq "RTL_SDR") {
        $sdrKey = Get-AwarenessSdrSignalKey -Signal $Signal
        if ($sdrKey) { return $sdrKey }
    }

    $id = ([string]$Signal.address).Trim()
    if (-not $id) { $id = ([string]$Signal.id).Trim() }
    if (-not $id -and $Signal.frequencyHz) { $id = [string]$Signal.frequencyHz }
    if (-not $id) { $id = ([string]$Signal.name).Trim() }
    if (-not $id) { $id = [guid]::NewGuid().ToString("N") }

    return "$($type.ToUpperInvariant())|$($id.ToUpperInvariant())"
}

function Get-AwarenessSdrSignalKey {
    param([object] $Signal)

    $frequency = ConvertTo-AwarenessNumber $Signal.frequencyHz
    if ($null -eq $frequency) { return $null }

    $classGroup = Get-AwarenessSdrClassGroup -Signal $Signal
    $bucketHz = Get-AwarenessSdrBucketHz -ClassGroup $classGroup
    $bucket = [long]([Math]::Round($frequency / $bucketHz) * $bucketHz)
    return "RTL_SDR|$classGroup|$bucket"
}

function Get-AwarenessSdrClassGroup {
    param([object] $Signal)

    $text = (Join-AwarenessNonEmptyText -Values @($Signal.deviceClass, $Signal.name, $Signal.notes, $Signal.modulation, $Signal.label) -Separator " ").ToLowerInvariant()
    if ($text -match "broadcast fm|fm/rbds") { return "broadcast-fm" }
    if ($text -match "military aviation|uhf air") { return "mil-airband" }
    if ($text -match "aviation airband|airband|am aviation|am/vor|nav beacon") { return "airband" }
    if ($text -match "noaa weather") { return "noaa-weather" }
    if ($text -match "vhf land mobile|business|railroad|marine|public service") { return "vhf-land-mobile" }
    if ($text -match "amateur radio 70cm|amateur 70cm") { return "amateur-70cm" }
    if ($text -match "amateur radio 2m|amateur 2m") { return "amateur-2m" }
    if ($text -match "lte|cellular|gsm|aws|pcs") { return "cellular" }
    if ($text -match "ads-b|mode s|uat") { return "adsb" }
    if ($text -match "ism|lora|fsk|ook") { return "ism" }
    if ($text -match "tv|broadcast auxiliary") { return "broadcast-tv" }
    if ($text -match "p25|trunked|public safety") { return "trunked-radio" }
    return "rf"
}

function Get-AwarenessSdrBucketHz {
    param([string] $ClassGroup)

    switch ($ClassGroup) {
        "broadcast-fm" { return 200000.0 }
        "cellular" { return 1000000.0 }
        "broadcast-tv" { return 1000000.0 }
        "adsb" { return 250000.0 }
        "ism" { return 500000.0 }
        default { return 250000.0 }
    }
}

function Join-AwarenessNonEmptyText {
    param([object[]] $Values, [string] $Separator = "; ")

    return (($Values | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | ForEach-Object { [string]$_ }) -join $Separator)
}

function ConvertTo-AwarenessNumber {
    param([object] $Value)
    if ($null -eq $Value) { return $null }
    $text = ([string]$Value).Trim().TrimEnd("%")
    $number = 0.0
    if ([double]::TryParse($text, [ref]$number)) { return $number }
    return $null
}

function ConvertTo-AwarenessIsoTime {
    param([object] $Milliseconds, [string] $Fallback)

    $value = 0L
    if ([long]::TryParse(([string]$Milliseconds), [ref]$value) -and $value -gt 0) {
        try {
            return [DateTimeOffset]::FromUnixTimeMilliseconds($value).UtcDateTime.ToString("o")
        } catch {}
    }
    return $Fallback
}

function Add-AwarenessTimelineEvent {
    param(
        [object] $SignalProfile,
        [string] $At,
        [string] $Kind,
        [string] $Summary,
        [object] $Data = $null
    )

    $timeline = @($SignalProfile.Timeline)
    $last = if ($timeline.Count -gt 0) { $timeline[-1] } else { $null }
    if ($last -and $last.Kind -eq $Kind -and $last.Summary -eq $Summary) {
        $last.LastAt = $At
        $last.Count = [int]$last.Count + 1
        return
    }

    $timeline += [pscustomobject][ordered]@{
        At = $At
        LastAt = $At
        Kind = $Kind
        Summary = $Summary
        Count = 1
        Data = $Data
    }
    if ($timeline.Count -gt 120) {
        $timeline = @($timeline | Select-Object -Last 120)
    }
    $SignalProfile.Timeline = @($timeline)
}

function Add-AwarenessRecentSighting {
    param(
        [object] $SignalProfile,
        [object] $Sighting
    )

    $sightings = @($SignalProfile.Sightings)
    $sightingId = [string]$Sighting.SightingId
    if ($sightingId -and @($sightings | Where-Object { [string]$_.SightingId -eq $sightingId }).Count -gt 0) {
        return
    }
    $last = if ($sightings.Count -gt 0) { $sightings[-1] } else { $null }
    $sameNode = $last -and $last.NodeId -eq $Sighting.NodeId
    $lastSignal = ConvertTo-AwarenessNumber $last.SignalStrengthNumeric
    $newSignal = ConvertTo-AwarenessNumber $Sighting.SignalStrengthNumeric
    $signalChanged = ($null -ne $lastSignal -and $null -ne $newSignal -and [Math]::Abs($newSignal - $lastSignal) -ge 3.0)
    $locationChanged = Test-AwarenessLocationChanged -Previous $last -Current $Sighting

    if ($sightingId -or -not $last -or -not $sameNode -or $signalChanged -or $locationChanged) {
        $sightings += $Sighting
        if ($sightings.Count -gt 240) {
            $sightings = @($sightings | Select-Object -Last 240)
        }
        $SignalProfile.Sightings = @($sightings)
    }
}

function Test-AwarenessLocationChanged {
    param(
        [object] $Previous,
        [object] $Current
    )

    if (-not $Previous -or -not $Current) { return $true }
    $prevLat = ConvertTo-AwarenessNumber $Previous.Latitude
    $prevLon = ConvertTo-AwarenessNumber $Previous.Longitude
    $curLat = ConvertTo-AwarenessNumber $Current.Latitude
    $curLon = ConvertTo-AwarenessNumber $Current.Longitude
    if ($null -eq $curLat -or $null -eq $curLon) { return $false }
    if ($null -eq $prevLat -or $null -eq $prevLon) { return $true }

    $meters = Get-AwarenessDistanceMeters -Lat1 $prevLat -Lon1 $prevLon -Lat2 $curLat -Lon2 $curLon
    return ($meters -ge 25.0)
}

function Get-AwarenessDistanceMeters {
    param(
        [double] $Lat1,
        [double] $Lon1,
        [double] $Lat2,
        [double] $Lon2
    )

    $earthMeters = 6371000.0
    $dLat = ($Lat2 - $Lat1) * [Math]::PI / 180.0
    $dLon = ($Lon2 - $Lon1) * [Math]::PI / 180.0
    $rLat1 = $Lat1 * [Math]::PI / 180.0
    $rLat2 = $Lat2 * [Math]::PI / 180.0
    $a = [Math]::Sin($dLat / 2.0) * [Math]::Sin($dLat / 2.0) +
        [Math]::Cos($rLat1) * [Math]::Cos($rLat2) *
        [Math]::Sin($dLon / 2.0) * [Math]::Sin($dLon / 2.0)
    return $earthMeters * 2.0 * [Math]::Atan2([Math]::Sqrt($a), [Math]::Sqrt(1.0 - $a))
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
    $completeTypes = @($Snapshot.completeTypes | ForEach-Object { ([string]$_).ToUpperInvariant() })
    $currentKeys = @{}
    $merged = 0
    $acknowledgedSightingIds = New-Object System.Collections.ArrayList

    foreach ($signal in $signals) {
        $key = Get-AwarenessSignalKey -Signal $signal
        $currentKeys[$key] = $true
        $journalSightings = @($signal.sightings)
        $knownSightingIds = @{}
        if ($state.Signals[$key]) {
            foreach ($storedSighting in @($state.Signals[$key].Sightings)) {
                $storedId = [string]$storedSighting.SightingId
                if ($storedId) { $knownSightingIds[$storedId] = $true }
            }
        }
        $newJournalSightings = @($journalSightings | Where-Object {
            $incomingId = [string]$_.id
            -not $incomingId -or -not $knownSightingIds.ContainsKey($incomingId)
        })
        $latestJournal = @($journalSightings | Sort-Object { [long]$_.capturedAt } | Select-Object -Last 1)
        $signalLat = if ($latestJournal.Count) { ConvertTo-AwarenessNumber $latestJournal[0].latitude } else { ConvertTo-AwarenessNumber $signal.latitude }
        $signalLon = if ($latestJournal.Count) { ConvertTo-AwarenessNumber $latestJournal[0].longitude } else { ConvertTo-AwarenessNumber $signal.longitude }
        $signalAccuracy = if ($latestJournal.Count) { ConvertTo-AwarenessNumber $latestJournal[0].accuracyMeters } else { ConvertTo-AwarenessNumber $signal.accuracyMeters }
        if ($null -eq $signalLat) { $signalLat = $nodeLat }
        if ($null -eq $signalLon) { $signalLon = $nodeLon }
        if ($null -eq $signalAccuracy) { $signalAccuracy = $nodeAccuracy }
        $signalStrength = $signal.signalStrength
        $signalStrengthNumber = ConvertTo-AwarenessNumber $signalStrength
        $existing = $state.Signals[$key]
        $created = $false
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
                PresenceState = "seen"
                LastPresentAt = $now
                LastMissingAt = ""
                NodeIds = @()
                Sightings = @()
                Timeline = @()
                EstimatedLatitude = $null
                EstimatedLongitude = $null
            }
            $state.Signals[$key] = $existing
            $created = $true
            Add-AwarenessTimelineEvent -SignalProfile $existing -At $now -Kind "first_seen" -Summary "First seen by $nodeName" -Data ([ordered]@{
                nodeId = $nodeId
                nodeName = $nodeName
                signal = $signalStrength
                latitude = $signalLat
                longitude = $signalLon
                type = [string]$signal.deviceClass
            })
        }

        if (-not $existing.Timeline) { $existing | Add-Member -NotePropertyName Timeline -NotePropertyValue @() -Force }
        if (-not $existing.PresenceState) { $existing | Add-Member -NotePropertyName PresenceState -NotePropertyValue "seen" -Force }
        if (-not $existing.LastPresentAt) { $existing | Add-Member -NotePropertyName LastPresentAt -NotePropertyValue $now -Force }
        if (-not $existing.LastMissingAt) { $existing | Add-Member -NotePropertyName LastMissingAt -NotePropertyValue "" -Force }
        if (-not $created -and $existing.PresenceState -eq "not_seen") {
            Add-AwarenessTimelineEvent -SignalProfile $existing -At $now -Kind "reappeared" -Summary "Seen again by $nodeName" -Data ([ordered]@{ nodeId = $nodeId; nodeName = $nodeName; signal = $signalStrength })
        }
        $existing.PresenceState = "seen"
        $existing.LastPresentAt = $now

        $newName = if ([string]$signal.name) { [string]$signal.name } else { $existing.Name }
        $newType = if ([string]$signal.deviceClass) { [string]$signal.deviceClass } else { $existing.SpecificType }
        $newManufacturer = if ([string]$signal.manufacturer) { [string]$signal.manufacturer } else { $existing.Manufacturer }
        $newThreat = if ([string]$signal.threatLevel) { [string]$signal.threatLevel } else { $existing.ThreatLevel }
        if (-not $created -and $newName -and $newName -ne $existing.Name) {
            Add-AwarenessTimelineEvent -SignalProfile $existing -At $now -Kind "name_changed" -Summary "Name changed from '$($existing.Name)' to '$newName'" -Data ([ordered]@{ old = $existing.Name; new = $newName })
        }
        if (-not $created -and $newType -and $newType -ne $existing.SpecificType) {
            Add-AwarenessTimelineEvent -SignalProfile $existing -At $now -Kind "type_changed" -Summary "Type changed from '$($existing.SpecificType)' to '$newType'" -Data ([ordered]@{ old = $existing.SpecificType; new = $newType })
        }
        if (-not $created -and $newManufacturer -and $newManufacturer -ne $existing.Manufacturer) {
            Add-AwarenessTimelineEvent -SignalProfile $existing -At $now -Kind "vendor_changed" -Summary "Vendor changed from '$($existing.Manufacturer)' to '$newManufacturer'" -Data ([ordered]@{ old = $existing.Manufacturer; new = $newManufacturer })
        }
        if (-not $created -and $newThreat -and $newThreat -ne $existing.ThreatLevel) {
            Add-AwarenessTimelineEvent -SignalProfile $existing -At $now -Kind "alert_changed" -Summary "Alert level changed from '$($existing.ThreatLevel)' to '$newThreat'" -Data ([ordered]@{ old = $existing.ThreatLevel; new = $newThreat })
        }

        $existing.Name = $newName
        $existing.Address = if ([string]$signal.address) { [string]$signal.address } else { $existing.Address }
        $existing.Type = if ([string]$signal.type) { [string]$signal.type } else { $existing.Type }
        $existing.SpecificType = $newType
        $existing.Manufacturer = $newManufacturer
        $existing.ThreatLevel = $newThreat
        $existing.Notes = if ([string]$signal.notes) { [string]$signal.notes } else { $existing.Notes }
        $existing.Channel = if ($signal.channel) { $signal.channel } else { $existing.Channel }
        $existing.FrequencyHz = if ($signal.frequencyHz) { $signal.frequencyHz } else { $existing.FrequencyHz }
        $existing.LastSeen = $now
        $existing.SeenCount = [int]$existing.SeenCount + $(if ($journalSightings.Count -gt 0) { $newJournalSightings.Count } else { 1 })
        $existing.LastSignal = $signal.signalStrength
        $existing.LastSignalNumeric = $signalStrengthNumber
        $strongestNumber = ConvertTo-AwarenessNumber $existing.StrongestSignalNumeric
        if ($null -ne $signalStrengthNumber -and ($null -eq $strongestNumber -or $signalStrengthNumber -gt $strongestNumber)) {
            if (-not $created -and ($null -eq $strongestNumber -or ($signalStrengthNumber - $strongestNumber) -ge 10.0)) {
                Add-AwarenessTimelineEvent -SignalProfile $existing -At $now -Kind "signal_jump" -Summary "Signal jumped from '$($existing.StrongestSignal)' to '$signalStrength'" -Data ([ordered]@{
                    old = $existing.StrongestSignal
                    new = $signalStrength
                    nodeId = $nodeId
                    nodeName = $nodeName
                })
            }
            $existing.StrongestSignal = $signal.signalStrength
            $existing.StrongestSignalNumeric = $signalStrengthNumber
        } elseif ($null -eq $existing.StrongestSignal -or [string]::IsNullOrWhiteSpace([string]$existing.StrongestSignal)) {
            $existing.StrongestSignal = $signal.signalStrength
            $existing.StrongestSignalNumeric = $signalStrengthNumber
        }

        $nodes = @($existing.NodeIds)
        if ($nodes -notcontains $nodeId) {
            $nodes += $nodeId
            if (-not $created) {
                Add-AwarenessTimelineEvent -SignalProfile $existing -At $now -Kind "new_node" -Summary "Also seen by $nodeName" -Data ([ordered]@{ nodeId = $nodeId; nodeName = $nodeName })
            }
        }
        $existing.NodeIds = @($nodes)

        foreach ($journal in $journalSightings) {
            if ([string]$journal.id) {
                [void]$acknowledgedSightingIds.Add([string]$journal.id)
            }
        }
        $incomingSightings = if ($journalSightings.Count -gt 0) { $newJournalSightings } else { @($null) }
        foreach ($journal in $incomingSightings) {
            $sightingAt = if ($null -ne $journal) { ConvertTo-AwarenessIsoTime -Milliseconds $journal.capturedAt -Fallback $now } else { $now }
            $sightingLat = if ($null -ne $journal) { ConvertTo-AwarenessNumber $journal.latitude } else { $signalLat }
            $sightingLon = if ($null -ne $journal) { ConvertTo-AwarenessNumber $journal.longitude } else { $signalLon }
            $sightingAccuracy = if ($null -ne $journal) { ConvertTo-AwarenessNumber $journal.accuracyMeters } else { $signalAccuracy }
            $sightingStrength = if ($null -ne $journal -and $null -ne $journal.signalStrength) { $journal.signalStrength } else { $signal.signalStrength }
            $sighting = [pscustomobject][ordered]@{
                SightingId = if ($null -ne $journal) { [string]$journal.id } else { "" }
                At = $sightingAt
                NodeId = $nodeId
                NodeName = $nodeName
                Latitude = $sightingLat
                Longitude = $sightingLon
                AccuracyMeters = $sightingAccuracy
                NodeLatitude = $sightingLat
                NodeLongitude = $sightingLon
                SignalStrength = $sightingStrength
                SignalStrengthNumeric = ConvertTo-AwarenessNumber $sightingStrength
            }
            $beforeSightings = @($existing.Sightings)
            Add-AwarenessRecentSighting -SignalProfile $existing -Sighting $sighting
            $afterSightings = @($existing.Sightings)
            if (-not $created -and $afterSightings.Count -gt $beforeSightings.Count -and (Test-AwarenessLocationChanged -Previous ($beforeSightings | Select-Object -Last 1) -Current $sighting)) {
                Add-AwarenessTimelineEvent -SignalProfile $existing -At $sightingAt -Kind "location_changed" -Summary "Seen from a new scan location by $nodeName" -Data ([ordered]@{
                    latitude = $sightingLat
                    longitude = $sightingLon
                    accuracyMeters = $sightingAccuracy
                    nodeId = $nodeId
                })
            }
        }

        $geo = @($existing.Sightings | Where-Object { $null -ne $_.Latitude -and $null -ne $_.Longitude })
        if ($geo.Count -gt 0) {
            $existing.EstimatedLatitude = ($geo | Measure-Object -Property Latitude -Average).Average
            $existing.EstimatedLongitude = ($geo | Measure-Object -Property Longitude -Average).Average
        }
        $merged++
    }

    if ($completeTypes.Count -gt 0) {
        foreach ($entry in @($state.Signals.GetEnumerator())) {
            $profile = $entry.Value
            $profileType = ([string]$profile.Type).ToUpperInvariant()
            if ($completeTypes -notcontains $profileType) { continue }
            if ($currentKeys.ContainsKey($entry.Key)) { continue }
            if (@($profile.NodeIds) -notcontains $nodeId) { continue }
            if (-not $profile.PresenceState) { $profile | Add-Member -NotePropertyName PresenceState -NotePropertyValue "seen" -Force }
            if ($profile.PresenceState -ne "not_seen") {
                $profile.PresenceState = "not_seen"
                $profile.LastMissingAt = $now
                Add-AwarenessTimelineEvent -SignalProfile $profile -At $now -Kind "not_seen" -Summary "Not seen by $nodeName in this complete scan" -Data ([ordered]@{ nodeId = $nodeId; nodeName = $nodeName; scanTypes = $completeTypes })
            }
        }
    }

    Save-AwarenessState -State $state
    return [pscustomobject][ordered]@{
        Merged = $merged
        TotalSignals = $state.Signals.Count
        UpdatedAt = $state.UpdatedAt
        AcknowledgedSightingIds = @($acknowledgedSightingIds)
    }
}

function Get-AwarenessRows {
    $state = Read-AwarenessState
    return @($state.Signals.GetEnumerator() | ForEach-Object {
        $signal = $_.Value
        $timeline = @($signal.Timeline)
        $latest = if ($timeline.Count -gt 0) { $timeline[-1].Summary } else { "profile updated" }
        [pscustomobject][ordered]@{
            Type = $signal.Type
            Signal = $signal.Name
            AddressOrFrequency = if ($signal.Address) { $signal.Address } else { $signal.FrequencyHz }
            StrengthOrPower = $signal.LastSignal
            Classification = $signal.SpecificType
            Confidence = $signal.ThreatLevel
            Details = "Seen $($signal.SeenCount)x from $(@($signal.NodeIds).Count) node(s); $latest"
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
            latestEvent = if (@($signal.Timeline).Count -gt 0) { @($signal.Timeline)[-1].Summary } else { "" }
            timelineCount = @($signal.Timeline).Count
            timeline = @($signal.Timeline | Select-Object -Last 12)
        }
    })

    return [ordered]@{
        schema = 1
        updatedAt = $state.UpdatedAt
        totalSignals = $signals.Count
        signals = $signals
    }
}

function ConvertTo-AwarenessSdrSignalPayload {
    param([object[]] $Signals)

    return @($Signals | ForEach-Object {
        [ordered]@{
            frequencyHz = $_.FrequencyHz
            frequency = $_.Frequency
            powerDb = $_.PowerDb
            bandwidth = $_.Bandwidth
            label = $_.Label
            modulation = $_.Modulation
            possibleUse = $_.PossibleUse
            confidence = $_.Confidence
            evidence = $_.Evidence
            description = $_.Description
            nextStep = $_.NextStep
            source = $_.Source
        }
    })
}

function Get-AwarenessSdrDeepScanPayload {
    $isRunning = @("queued", "running") -contains $script:AwarenessSdrDeepScan.State
    $payload = if ($isRunning) {
        [ordered]@{
            schema = 1
            merged = 0
            totalSignals = 0
            updatedAt = (Get-Date).ToUniversalTime().ToString("o")
            signals = @()
        }
    } else {
        Get-AwarenessSyncPayload
    }
    $signals = @($script:AwarenessSdrDeepScan.SdrSignals)
    $payload["ok"] = ($script:AwarenessSdrDeepScan.State -ne "failed")
    $payload["sdrScan"] = [ordered]@{
        id = $script:AwarenessSdrDeepScan.Id
        state = $script:AwarenessSdrDeepScan.State
        requestedAt = $script:AwarenessSdrDeepScan.RequestedAt
        startedAt = $script:AwarenessSdrDeepScan.StartedAt
        finishedAt = $script:AwarenessSdrDeepScan.FinishedAt
        message = $script:AwarenessSdrDeepScan.Message
        error = $script:AwarenessSdrDeepScan.Error
        running = @("queued", "running") -contains $script:AwarenessSdrDeepScan.State
        completed = ($script:AwarenessSdrDeepScan.State -eq "completed")
    }
    $payload["sdrSignals"] = ConvertTo-AwarenessSdrSignalPayload -Signals $signals
    return $payload
}

function Request-AwarenessSdrDeepScan {
    if (@("queued", "running") -contains $script:AwarenessSdrDeepScan.State) {
        return $script:AwarenessSdrDeepScan.Id
    }

    $script:AwarenessSdrDeepScan = [ordered]@{
        Id = [guid]::NewGuid().ToString("N")
        State = "queued"
        RequestedAt = (Get-Date).ToUniversalTime().ToString("o")
        StartedAt = ""
        FinishedAt = ""
        Message = "PC SDR deep scan queued."
        Error = ""
        SdrSignals = @()
    }
    return $script:AwarenessSdrDeepScan.Id
}

function Invoke-PendingAwarenessSdrDeepScan {
    param([string] $LogPath)

    if (@("queued", "running") -notcontains $script:AwarenessSdrDeepScan.State) { return $false }
    try {
        if (-not (Get-Command Start-SdrPowerScan -ErrorAction SilentlyContinue) -or
            -not (Get-Command Complete-SdrPowerScan -ErrorAction SilentlyContinue)) {
            throw "SDR deep scan is not available"
        }
        if ($script:AwarenessSdrDeepScan.State -eq "queued") {
            [void](Start-SdrPowerScan)
            $script:AwarenessSdrDeepScan.State = "running"
            $script:AwarenessSdrDeepScan.StartedAt = (Get-Date).ToUniversalTime().ToString("o")
            $script:AwarenessSdrDeepScan.Message = "PC SDR deep scan running."
            return $true
        }

        $result = Complete-SdrPowerScan
        if (-not $result.Completed) { return $false }
        if ($result.Error) { throw $result.Error }
        $hits = @($result.Signals)
        $script:AwarenessSdrDeepScan.SdrSignals = $hits
        $script:AwarenessSdrDeepScan.State = "completed"
        $script:AwarenessSdrDeepScan.Message = "PC SDR deep scan completed with $($hits.Count) RF peak(s)."
    } catch {
        $script:AwarenessSdrDeepScan.State = "failed"
        $script:AwarenessSdrDeepScan.Error = $_.Exception.Message
        $script:AwarenessSdrDeepScan.Message = "PC SDR deep scan failed."
        if ($LogPath) {
            Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SDR deep scan error: $($_.Exception.Message)" -ErrorAction SilentlyContinue
        }
    } finally {
        if (@("completed", "failed") -contains $script:AwarenessSdrDeepScan.State) {
            $script:AwarenessSdrDeepScan.FinishedAt = (Get-Date).ToUniversalTime().ToString("o")
        }
    }
    return $true
}

function Start-AwarenessSyncServer {
    param(
        [string] $BindAddress = "0.0.0.0",
        [int] $Port = 8766,
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
            $path = (($request.Path -split '\?')[0]).ToLowerInvariant()
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
                $payload = @{
                    schema = 1
                    merged = $merge.Merged
                    totalSignals = $merge.TotalSignals
                    updatedAt = $merge.UpdatedAt
                    acknowledgedSightingIds = @($merge.AcknowledgedSightingIds)
                    signals = @()
                }
                Send-AwarenessTcpJsonResponse -Client $client -Body $payload
                $handled++
                continue
            }
            if ($request.Method -eq "GET" -and $path -eq "/snifferops/sdr/deep-scan/status") {
                Send-AwarenessTcpJsonResponse -Client $client -Body (Get-AwarenessSdrDeepScanPayload)
                $handled++
                continue
            }
            if ($request.Method -eq "POST" -and $path -eq "/snifferops/sdr/deep-scan") {
                if (-not (Get-Command Start-SdrPowerScan -ErrorAction SilentlyContinue)) {
                    Send-AwarenessTcpJsonResponse -Client $client -StatusCode 503 -Body @{ error = "SDR deep scan is not available" }
                    $handled++
                    continue
                }
                [void](Request-AwarenessSdrDeepScan)
                Send-AwarenessTcpJsonResponse -Client $client -StatusCode 202 -Body (Get-AwarenessSdrDeepScanPayload)
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

    $Client.ReceiveTimeout = 15000
    $Client.SendTimeout = 15000
    $stream = $Client.GetStream()
    $headerBytes = New-Object System.Collections.Generic.List[byte]
    $headerEnd = -1
    while ($headerEnd -lt 0) {
        $value = $stream.ReadByte()
        if ($value -lt 0) { break }
        $headerBytes.Add([byte]$value)
        $count = $headerBytes.Count
        if ($count -ge 4 -and
            $headerBytes[$count - 4] -eq 13 -and
            $headerBytes[$count - 3] -eq 10 -and
            $headerBytes[$count - 2] -eq 13 -and
            $headerBytes[$count - 1] -eq 10) {
            $headerEnd = $count - 4
        }
        if ($count -gt 65536) { throw "HTTP request headers are too large" }
    }

    if ($headerEnd -lt 0) { throw "Invalid HTTP request" }
    $headerText = [System.Text.Encoding]::ASCII.GetString($headerBytes.ToArray(), 0, $headerEnd)
    $contentLength = 0
    foreach ($line in $headerText -split "`r`n") {
        if ($line -match '^Content-Length:\s*(\d+)') { $contentLength = [int]$Matches[1] }
    }
    if ($contentLength -gt 32MB) { throw "HTTP request body is too large" }

    $bodyBytes = [byte[]]::new($contentLength)
    $offset = 0
    while ($offset -lt $contentLength) {
        $read = $stream.Read($bodyBytes, $offset, $contentLength - $offset)
        if ($read -le 0) { throw "HTTP request body ended early" }
        $offset += $read
    }

    $body = if ($contentLength -gt 0) {
        [System.Text.Encoding]::UTF8.GetString($bodyBytes)
    } else {
        ""
    }
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
        202 { "Accepted" }
        503 { "Service Unavailable" }
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
