# SignalLens contract for SnifferOps Windows.
#
# A "lens" is the class-appropriate viewer for a detected SDR signal. Instead of
# forcing every signal through analog audio demodulation, each signal class
# routes to the lens that knows how to present it.
#
# A lens is a plain PSCustomObject (built by a New-*Lens factory in its own file)
# exposing this contract. PSCustomObject + ScriptMethod is used instead of a
# PowerShell `class` so each lens file can be dot-sourced and unit-tested in
# isolation without parse-time base-type resolution problems in Windows PS 5.1.
#
# Required properties:
#   Name        [string]  stable id, e.g. "BroadcastFM"
#   Kind        [string]  "voice" or "data" (drives chooser grouping)
#   Implemented [bool]     $true = real decoder; $false = roadmap stub
#   DisplayName [string]  short UI label, e.g. "Listen - Broadcast FM (WFM)"
#
# Required methods:
#   CanHandle($signal)    -> [bool]   does this lens apply to the signal row?
#   GetDisplayName()      -> [string] short label shown in chooser/UI
#   Activate($signal)     -> [pscustomobject] directive (see below)
#   Deactivate()          -> void     cleanup hook (audio teardown is central)
#
# $signal is an SDR row with at least: FrequencyHz [long], Label, Modulation.
#
# Activate() returns a directive the UI layer interprets, so lenses stay free of
# WPF/audio dependencies and remain testable:
#   Voice: [pscustomobject]@{ Kind='listen'; Mode='wbfm'|'nfm'|'am';
#                             AllowModeOverride=[bool]; Frequency=[long]; Title=[string] }
#   Stub:  [pscustomobject]@{ Kind='notimplemented'; Message=[string] }

function Get-SignalFrequencyMHz {
    param([object] $Signal)

    if ($null -eq $Signal) { return $null }
    $hz = $Signal.FrequencyHz
    if ($null -eq $hz -or "$hz" -eq "") { return $null }

    $parsed = 0L
    if (-not [long]::TryParse("$hz", [ref] $parsed)) { return $null }
    return $parsed / 1000000.0
}

# Builds a contract-compliant lens object from scriptblocks. Keeps each lens
# file small. CanHandle/Activate are invoked with the signal row as $args[0].
function New-LensObject {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [ValidateSet('voice', 'data')] [string] $Kind,
        [Parameter(Mandatory)] [bool] $Implemented,
        [Parameter(Mandatory)] [string] $DisplayName,
        [Parameter(Mandatory)] [scriptblock] $CanHandle,
        [Parameter(Mandatory)] [scriptblock] $Activate,
        [scriptblock] $Deactivate = { }
    )

    $lens = [pscustomobject][ordered]@{
        Name        = $Name
        Kind        = $Kind
        Implemented = $Implemented
        DisplayName = $DisplayName
    }
    Add-Member -InputObject $lens -MemberType ScriptMethod -Name CanHandle -Value $CanHandle
    Add-Member -InputObject $lens -MemberType ScriptMethod -Name Activate -Value $Activate
    Add-Member -InputObject $lens -MemberType ScriptMethod -Name Deactivate -Value $Deactivate
    Add-Member -InputObject $lens -MemberType ScriptMethod -Name GetDisplayName -Value { $this.DisplayName }
    return $lens
}

function Test-SignalLens {
    param([object] $Lens)

    foreach ($prop in 'Name', 'Kind', 'Implemented', 'DisplayName') {
        if (-not $Lens.PSObject.Properties.Match($prop).Count) {
            throw "Lens is missing required property '$prop'."
        }
    }
    foreach ($method in 'CanHandle', 'GetDisplayName', 'Activate', 'Deactivate') {
        if (-not $Lens.PSObject.Methods.Match($method).Count) {
            throw "Lens '$($Lens.Name)' is missing required method '$method'."
        }
    }
    if ($Lens.Kind -ne 'voice' -and $Lens.Kind -ne 'data') {
        throw "Lens '$($Lens.Name)' has invalid Kind '$($Lens.Kind)' (expected voice|data)."
    }
    return $true
}
