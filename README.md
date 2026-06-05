# SnifferOps Windows Companion

This branch contains the Windows companion version of SnifferOps.

Use this branch on the Windows machine that hosts the RTL-SDR dongle. The companion can start `rtl_tcp` so the Android app can use Network SDR data over the local network, and it also includes Windows-side SDR testing, scanning, ADS-B helpers, and radio listening tools.

For the Samsung-focused Android phone app and Samsung watch monitor companion, use the `codex/android-mobile-app` branch.

## Launch

From Windows Explorer:

```text
windows\Launch-SnifferOps-Windows.bat
```

From PowerShell:

```powershell
powershell -STA -ExecutionPolicy Bypass -File windows\SnifferOps.Windows.ps1
```

## RTL-SDR Setup

Install the RTL-SDR Blog command-line tools into the ignored `tools/` folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-rtl-sdr-blog-tools.ps1
```

After binding the dongle to WinUSB, start the server for Android Network SDR mode:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-rtl-tcp.ps1
```

Optional parameters:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-rtl-tcp.ps1 -BindAddress 0.0.0.0 -Port 1234
```

Use this helper to verify the dongle can be opened:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test-rtl-sdr.ps1
```

## Main Controls

- `START WINDOWS RTL SERVER` runs `scripts\start-rtl-tcp.ps1` for the Android app's Network SDR feed.
- `CONNECT NETWORK SDR` starts `rtl_tcp` from inside the Windows companion.
- `STOP RTL_TCP` stops the local `rtl_tcp` server.
- `TEST DONGLE` runs `rtl_test.exe -t`.
- `FM / AM RADIO TUNER` opens the local Windows radio listener.
- `REFRESH` updates local Wi-Fi, Bluetooth, SDR, and LAN endpoint status.
- `OPEN LOGS` opens the latest `rtl_tcp` error log.

## Icon

The Windows app and desktop shortcut use `windows\assets\snifferops.ico`, generated from `windows\assets\snifferops-tile.png`.

## Font

The Windows UI ships Spy Agency font assets under `windows\assets\fonts\` and loads them at runtime, so the companion keeps its display styling without requiring a system font install.

## Notes

Runtime captures, logs, generated ADS-B map output, screenshots, and downloaded RTL-SDR tools are intentionally ignored and should not be committed.
