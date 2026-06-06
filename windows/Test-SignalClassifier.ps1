# Headless unit test for WiFi/Bluetooth/SDR explanation rules.
# Run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\Test-SignalClassifier.ps1
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "SignalClassifier.ps1")

$failures = 0
function Assert($desc, $cond) {
    if ($cond) { "PASS  $desc" } else { "FAIL  $desc"; $script:failures++ }
}

function Wifi($name, $channel = "6", $security = "WPA2-Personal / CCMP") {
    [pscustomobject]@{
        Name = $name
        Channel = $channel
        Security = $security
    }
}

function Bt($name, $status = "OK") {
    [pscustomobject]@{
        Name = $name
        Status = $status
    }
}

Write-Host "== Signal explanation tests ==" -ForegroundColor Cyan

$camera = Get-WifiSignalExplanation -Wifi (Wifi "Ring Doorbell Setup" "11" "Open")
Assert "WiFi camera/doorbell keyword" ($camera.SpecificType -match "camera|doorbell" -and $camera.Confidence -eq "High" -and $camera.Evidence -match "open security")

$flock = Get-WifiSignalExplanation -Wifi (Wifi "FlockSafety-Unit")
Assert "WiFi Flock keyword" ($flock.SpecificType -match "Flock" -and $flock.Confidence -eq "High")

$router = Get-WifiSignalExplanation -Wifi (Wifi "NETGEAR-5G" "149")
Assert "WiFi router keyword and 5GHz evidence" ($router.SpecificType -match "router|gateway|access point" -and $router.Evidence -match "5 GHz")

$tv = Get-WifiSignalExplanation -Wifi (Wifi "LivingRoom Roku")
Assert "WiFi media device keyword" ($tv.SpecificType -match "TV|streaming|media")

$hidden = Get-WifiSignalExplanation -Wifi (Wifi "<hidden>")
Assert "Hidden WiFi does not go blank" ($hidden.SpecificType -match "Hidden" -and $hidden.Confidence -eq "Medium")

$audio = Get-BluetoothSignalExplanation -Device (Bt "Sony WH-1000XM")
Assert "Bluetooth audio keyword" ($audio.SpecificType -match "headphones|audio")

$adapter = Get-BluetoothSignalExplanation -Device (Bt "Intel Bluetooth Adapter")
Assert "Bluetooth adapter keyword" ($adapter.SpecificType -match "adapter|radio")

$fm = Get-SdrSignalExplanation -Frequency 88500000
Assert "SDR FM broadcast band" ($fm.SpecificType -match "Broadcast FM" -and $fm.Modulation -match "WFM")

$ism = Get-SdrSignalExplanation -Frequency 433920000
Assert "SDR 433 MHz ISM beats amateur fallback" ($ism.SpecificType -match "433 MHz ISM" -and $ism.Modulation -match "OOK|FSK")

$adsb = Get-SdrSignalExplanation -Frequency 1090000000
Assert "SDR 1090 ADS-B beats DME range" ($adsb.SpecificType -match "ADS-B" -and $adsb.Confidence -eq "High")

Write-Host ""
if ($failures -eq 0) {
    Write-Host "ALL SIGNAL EXPLANATION TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures SIGNAL EXPLANATION TEST(S) FAILED" -ForegroundColor Red
    exit 1
}
