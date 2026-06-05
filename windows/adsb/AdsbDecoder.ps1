# Pure ADS-B (Mode S extended squitter) decoder. No WPF, no audio, no I/O —
# just frame hex in, aircraft objects out, so it can be unit-tested headless.
#
# Handles DF17/DF18 messages:
#   TC 1-4   : aircraft identification (callsign)
#   TC 9-18  : airborne position (barometric altitude + CPR lat/lon)
#   TC 19    : airborne velocity (ground speed + track)
# Position needs a matched even/odd CPR frame pair (global decode).

function Convert-HexToBytes {
    param([string] $Hex)
    $Hex = ($Hex -replace '[^0-9A-Fa-f]', '')
    if ($Hex.Length % 2 -ne 0) { return @() }
    $bytes = New-Object byte[] ($Hex.Length / 2)
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        $bytes[$i] = [Convert]::ToByte($Hex.Substring($i * 2, 2), 16)
    }
    return ,$bytes
}

# Extract $count bits from a byte array starting at absolute bit offset $start
# (bit 0 = MSB of byte 0). Returns an unsigned integer.
function Get-Bits {
    param([byte[]] $Bytes, [int] $Start, [int] $Count)
    $value = [long]0
    for ($i = 0; $i -lt $Count; $i++) {
        $bitIndex = $Start + $i
        $byteIndex = [int][math]::Floor($bitIndex / 8)
        $bitInByte = 7 - ($bitIndex % 8)
        $bit = ($Bytes[$byteIndex] -shr $bitInByte) -band 1
        $value = ($value -shl 1) -bor $bit
    }
    return $value
}

function Get-AdsbDownlinkFormat {
    param([byte[]] $Bytes)
    if ($Bytes.Length -lt 1) { return -1 }
    return [int]($Bytes[0] -shr 3)
}

function Get-AdsbIcao {
    param([byte[]] $Bytes)
    if ($Bytes.Length -lt 4) { return $null }
    return ('{0:X2}{1:X2}{2:X2}' -f $Bytes[1], $Bytes[2], $Bytes[3])
}

function Get-AdsbTypeCode {
    param([byte[]] $Bytes)
    if ($Bytes.Length -lt 5) { return -1 }
    # ME field starts at byte 4; TC is its top 5 bits.
    return [int]($Bytes[4] -shr 3)
}

function Get-AdsbCallsign {
    param([byte[]] $Bytes)
    if ($Bytes.Length -lt 11) { return $null }
    $charset = '#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######'
    # ME bit layout: TC(5) + CAT(3) then 8 x 6-bit chars. ME starts at bit 32,
    # chars start at bit 32+8 = 40.
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt 8; $i++) {
        $code = [int](Get-Bits -Bytes $Bytes -Start (40 + $i * 6) -Count 6)
        $ch = $charset[$code]
        [void]$sb.Append($ch)
    }
    return ($sb.ToString() -replace '#', '').Trim()
}

# Decode the 12-bit barometric altitude field (TC 9-18). Returns feet or $null.
function Get-AdsbAltitude {
    param([byte[]] $Bytes)
    if ($Bytes.Length -lt 11) { return $null }
    # ALT field: ME bits 8..19 -> absolute bits 40..51.
    $alt = [int](Get-Bits -Bytes $Bytes -Start 40 -Count 12)
    if ($alt -eq 0) { return $null }
    $qBit = ($alt -band 0x10) -shr 4
    if ($qBit -eq 1) {
        $n = (($alt -band 0xFE0) -shr 1) -bor ($alt -band 0xF)
        return ($n * 25 - 1000)
    }
    # Q=0 (Gillham/25ft mode) is rare for ADS-B; report raw-derived estimate skipped.
    return $null
}

function Get-AdsbCprFrame {
    param([byte[]] $Bytes)
    if ($Bytes.Length -lt 11) { return $null }
    # Airborne position ME layout (absolute bits):
    #   T   : bit 52   F : bit 53
    #   LAT : bits 54..70 (17)   LON : bits 71..87 (17)
    $f = [int](Get-Bits -Bytes $Bytes -Start 53 -Count 1)
    $latCpr = [int](Get-Bits -Bytes $Bytes -Start 54 -Count 17)
    $lonCpr = [int](Get-Bits -Bytes $Bytes -Start 71 -Count 17)
    return [pscustomobject]@{
        OddFlag = $f          # 0 = even, 1 = odd
        LatCpr  = $latCpr
        LonCpr  = $lonCpr
    }
}

# Number of longitude zones at a given latitude (NL function).
function Get-CprNL {
    param([double] $Lat)
    $absLat = [math]::Abs($Lat)
    if ($absLat -lt 1e-9) { return 59 }
    if ([math]::Abs($absLat - 87.0) -lt 1e-9) { return 2 }
    if ($absLat -gt 87.0) { return 1 }
    $nz = 15.0
    $a = 1.0 - [math]::Cos([math]::PI / (2.0 * $nz))
    $b = [math]::Pow([math]::Cos([math]::PI / 180.0 * $absLat), 2)
    $nl = 2.0 * [math]::PI / [math]::Acos(1.0 - $a / $b)
    return [int][math]::Floor($nl)
}

function Get-FloorMod {
    param([double] $A, [double] $B)
    return $A - $B * [math]::Floor($A / $B)
}

# Global airborne CPR position decode from a matched even+odd pair.
# $mostRecentOdd: 0 if the even frame was most recent, 1 if the odd frame was.
function Resolve-CprPosition {
    param(
        [object] $Even,   # CPR frame with OddFlag=0
        [object] $Odd,    # CPR frame with OddFlag=1
        [int]    $MostRecentOdd = 1
    )
    $nz = 15.0
    $dLatEven = 360.0 / (4.0 * $nz)
    $dLatOdd  = 360.0 / (4.0 * $nz - 1.0)

    $latCprEven = $Even.LatCpr / 131072.0
    $latCprOdd  = $Odd.LatCpr / 131072.0
    $lonCprEven = $Even.LonCpr / 131072.0
    $lonCprOdd  = $Odd.LonCpr / 131072.0

    $j = [math]::Floor(59.0 * $latCprEven - 60.0 * $latCprOdd + 0.5)
    $rLatEven = $dLatEven * ((Get-FloorMod -A $j -B 60.0) + $latCprEven)
    $rLatOdd  = $dLatOdd  * ((Get-FloorMod -A $j -B 59.0) + $latCprOdd)
    if ($rLatEven -ge 270.0) { $rLatEven -= 360.0 }
    if ($rLatOdd  -ge 270.0) { $rLatOdd  -= 360.0 }

    if ((Get-CprNL -Lat $rLatEven) -ne (Get-CprNL -Lat $rLatOdd)) {
        return $null   # straddling a latitude zone boundary; wait for a fresh pair
    }

    if ($MostRecentOdd -eq 0) {
        $lat = $rLatEven
        $nl = Get-CprNL -Lat $rLatEven
        $ni = [math]::Max($nl, 1)
        $m = [math]::Floor($lonCprEven * ($nl - 1) - $lonCprOdd * $nl + 0.5)
        $lon = (360.0 / $ni) * ((Get-FloorMod -A $m -B $ni) + $lonCprEven)
    } else {
        $lat = $rLatOdd
        $nl = Get-CprNL -Lat $rLatOdd
        $ni = [math]::Max($nl - 1, 1)
        $m = [math]::Floor($lonCprEven * ($nl - 1) - $lonCprOdd * $nl + 0.5)
        $lon = (360.0 / $ni) * ((Get-FloorMod -A $m -B $ni) + $lonCprOdd)
    }
    if ($lon -ge 180.0) { $lon -= 360.0 }

    return [pscustomobject]@{ Lat = [math]::Round($lat, 5); Lon = [math]::Round($lon, 5) }
}

# Airborne velocity (TC 19, subtype 1/2 ground speed). Returns speed(kt)+track(deg).
function Get-AdsbVelocity {
    param([byte[]] $Bytes)
    if ($Bytes.Length -lt 11) { return $null }
    $subType = [int](Get-Bits -Bytes $Bytes -Start 37 -Count 3)
    if ($subType -ne 1 -and $subType -ne 2) { return $null }
    $ewSign = [int](Get-Bits -Bytes $Bytes -Start 45 -Count 1)
    $ewVel  = [int](Get-Bits -Bytes $Bytes -Start 46 -Count 10)
    $nsSign = [int](Get-Bits -Bytes $Bytes -Start 56 -Count 1)
    $nsVel  = [int](Get-Bits -Bytes $Bytes -Start 57 -Count 10)
    if ($ewVel -eq 0 -or $nsVel -eq 0) { return $null }
    $vx = ($ewVel - 1); if ($ewSign -eq 1) { $vx = -$vx }
    $vy = ($nsVel - 1); if ($nsSign -eq 1) { $vy = -$vy }
    if ($subType -eq 2) { $vx *= 4; $vy *= 4 }   # supersonic
    $speed = [math]::Sqrt($vx * $vx + $vy * $vy)
    $track = [math]::Atan2($vx, $vy) * 180.0 / [math]::PI
    if ($track -lt 0) { $track += 360.0 }
    return [pscustomobject]@{
        SpeedKt   = [int][math]::Round($speed)
        TrackDeg  = [int][math]::Round($track)
    }
}

# Top-level: take an array of raw frame strings (with or without * ; markers),
# return an array of aircraft objects keyed by ICAO with the best data seen.
function Convert-AdsbFrames {
    param([string[]] $Frames)

    $aircraft = @{}
    foreach ($raw in $Frames) {
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        $bytes = Convert-HexToBytes $raw
        if ($bytes.Length -ne 14) { continue }   # only long (112-bit) squitters
        $df = Get-AdsbDownlinkFormat -Bytes $bytes
        if ($df -ne 17 -and $df -ne 18) { continue }

        $icao = Get-AdsbIcao -Bytes $bytes
        if (-not $icao) { continue }
        if (-not $aircraft.ContainsKey($icao)) {
            $aircraft[$icao] = [pscustomobject]@{
                Icao     = $icao
                Callsign = $null
                Altitude = $null
                SpeedKt  = $null
                TrackDeg = $null
                Lat      = $null
                Lon      = $null
                Messages = 0
                EvenCpr  = $null
                OddCpr   = $null
                LastCprOdd = 1
            }
        }
        $ac = $aircraft[$icao]
        $ac.Messages++

        $tc = Get-AdsbTypeCode -Bytes $bytes
        if ($tc -ge 1 -and $tc -le 4) {
            $cs = Get-AdsbCallsign -Bytes $bytes
            if ($cs) { $ac.Callsign = $cs }
        }
        elseif ($tc -ge 9 -and $tc -le 18) {
            $alt = Get-AdsbAltitude -Bytes $bytes
            if ($null -ne $alt) { $ac.Altitude = $alt }
            $cpr = Get-AdsbCprFrame -Bytes $bytes
            if ($cpr) {
                if ($cpr.OddFlag -eq 0) { $ac.EvenCpr = $cpr } else { $ac.OddCpr = $cpr }
                $ac.LastCprOdd = $cpr.OddFlag
                if ($ac.EvenCpr -and $ac.OddCpr) {
                    $pos = Resolve-CprPosition -Even $ac.EvenCpr -Odd $ac.OddCpr -MostRecentOdd $ac.LastCprOdd
                    if ($pos) { $ac.Lat = $pos.Lat; $ac.Lon = $pos.Lon }
                }
            }
        }
        elseif ($tc -eq 19) {
            $vel = Get-AdsbVelocity -Bytes $bytes
            if ($vel) { $ac.SpeedKt = $vel.SpeedKt; $ac.TrackDeg = $vel.TrackDeg }
        }
    }

    return @($aircraft.Values | ForEach-Object {
        [pscustomobject][ordered]@{
            Icao     = $_.Icao
            Callsign = if ($_.Callsign) { $_.Callsign } else { "" }
            Altitude = $_.Altitude
            SpeedKt  = $_.SpeedKt
            TrackDeg = $_.TrackDeg
            Lat      = $_.Lat
            Lon      = $_.Lon
            Messages = $_.Messages
        }
    })
}
