# SnifferOps

SnifferOps is a passive signal scanner for Wi-fi, Bluetooth, NFC, and by using the Windows companion app it is able to use an RTL SDR Blog V4 for SDR scanning in the mobile app as well as the Windows companion app. The Android app is tailored toward Samsung devices, and inlcudes a Samsung Watch app that shows status when the Android app is on.

## Choose A Version

- Android app for Samsung phones, with Samsung watch monitor companion: [`codex/android-mobile-app`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/android-mobile-app)
- Windows companion for the Windows machine hosting the RTL-SDR server: [`codex/windows-companion`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/windows-companion)

## How They Link

Use the Windows companion to start the Windows RTL server when the Android app needs Network SDR data. Then connect from the Android app's SDR screen using the Windows machine's LAN IP address and RTL TCP port.

`main` is intentionally kept as this landing page. App source lives in the version branches above.
