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
- `PC CONNECTION SETTINGS` shows the host and ports the phone should use (prefers Tailscale when it is running, otherwise the LAN address).
- `REFRESH` updates local Wi-Fi, Bluetooth, SDR, and LAN endpoint status.
- `OPEN LOGS` opens the latest `rtl_tcp` error log.

## Offline Awareness Map

The awareness panel in the header is a live miniature of the offline map; clicking it opens the full map window. The map draws a real map background from standard slippy tiles (dark CARTO / OpenStreetMap style): tiles download automatically the first time you view an area while online and are cached under the ignored `data\map-tiles\` folder, after which that area renders fully offline. With no cached tiles for an area it falls back to a plain coordinate grid, so the map never needs the internet to function. Drag to pan, scroll to zoom, click a dot for the signal's profile.

Signals synced from the phone (`/snifferops/sync`) are placed in tiers:

1. **GPS** (solid dot) - the signal has phone-GPS located sightings; it plots at their average.
2. **Inferred, co-seen GPS** (dashed dot) - the signal has no GPS of its own, but the node that saw it reported GPS fixes for other signals close in time. It is placed from those fixes, weighted toward the nearest in time.
3. **Inferred, node area** (hollow dashed dot) - no time-correlated fix exists, so the signal lands at its observing node's usual area: the average of that node's own GPS fixes, or - for a node that never has GPS, like this PC - the average position of GPS-placed signals the node also sees.
4. **Unplaced** - nothing GPS-related was ever observed alongside the signal; it is counted in the status bar but not drawn.

Colors match the scanner tiles (Wi-Fi green, Bluetooth blue, cellular amber, SDR purple), and Watch/Alert signals get a warning ring. The map refreshes automatically as phone sync snapshots arrive.

The placement engine is headlessly testable:

```powershell
powershell -ExecutionPolicy Bypass -File windows\Test-OfflineMap.ps1
```

## Awareness Sync Endpoints

The companion listens on the sync port (default 8765) for the phone app:

- `GET /snifferops/health` - reachability check.
- `GET /snifferops/awareness` - the merged signal awareness state.
- `POST /snifferops/sync` - merge a phone snapshot (signals plus GPS location) into the awareness log.
- `POST /snifferops/sdr/deep-scan` and `GET /snifferops/sdr/deep-scan/status` - ask the PC to run an SDR spectrum sweep and poll its result.

## Icon

The Windows app and desktop shortcut use `windows\assets\snifferops.ico`, generated from `windows\assets\snifferops-tile.png`.

## Font

The Windows UI ships Spy Agency font assets under `windows\assets\fonts\` and loads them at runtime, so the companion keeps its display styling without requiring a system font install.

## Notes

Runtime captures, logs, generated ADS-B map output, screenshots, and downloaded RTL-SDR tools are intentionally ignored and should not be committed.
