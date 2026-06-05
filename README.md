# SnifferOps

SnifferOps is a passive signal scanner for Wi-Fi, Bluetooth, NFC, and SDR workflows. The Samsung-focused Android app can use an RTL-SDR Blog V4 through the polished Windows companion app, which also supports Windows-side SDR scanning with its own desktop UI, app icon, and RTL server controls. The Android branch includes the Samsung Watch status monitor companion.

## Choose A Version

- Android app for Samsung phones, with Samsung watch monitor companion: [`codex/android-mobile-app`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/android-mobile-app)
- Windows companion for the Windows machine hosting the RTL-SDR server: [`codex/windows-companion`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/windows-companion)

## How They Link

Use the Windows companion to start the Windows RTL server when the Android app needs Network SDR data. Then connect from the Android app's SDR screen using the Windows machine's LAN IP address and RTL TCP port.

`main` is intentionally kept as this landing page. App source lives in the version branches above.
