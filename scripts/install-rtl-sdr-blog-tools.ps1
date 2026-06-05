param(
    [string] $Destination = "tools\rtl-sdr-blog"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root $Destination
$zip = Join-Path $dest "Release.zip"

New-Item -ItemType Directory -Force -Path $dest | Out-Null

$release = Invoke-RestMethod -Uri "https://api.github.com/repos/rtlsdrblog/rtl-sdr-blog/releases/latest"
$asset = $release.assets | Where-Object { $_.name -eq "Release.zip" } | Select-Object -First 1
if (-not $asset) {
    throw "Could not find Release.zip in the latest rtl-sdr-blog release."
}

Write-Host "Downloading rtl-sdr-blog $($release.tag_name)..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip

Write-Host "Extracting to $dest..."
Expand-Archive -Path $zip -DestinationPath $dest -Force

Write-Host "Installed RTL-SDR Blog tools to $dest"
