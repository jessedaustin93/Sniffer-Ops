$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$rtlTest = Join-Path $root "tools\rtl-sdr-blog\x64\rtl_test.exe"

if (-not (Test-Path $rtlTest)) {
    throw "rtl_test.exe was not found at $rtlTest"
}

& $rtlTest -t
