# SnifferOps

SnifferOps is split into dedicated version branches so the Android/Samsung app and the Windows companion are not mashed together on `main`.

## Choose A Version

- Android app for Samsung phones, with Samsung watch monitor companion: [`codex/android-mobile-app`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/android-mobile-app)
- Windows companion for the Windows machine hosting the RTL-SDR server: [`codex/windows-companion`](https://github.com/jessedaustin93/Sniffer-Ops/tree/codex/windows-companion)

## How They Link

Use the Windows companion to start the Windows RTL server when the Android app needs Network SDR data. Then connect from the Android app's SDR screen using the Windows machine's LAN IP address and RTL TCP port.

`main` is intentionally kept as this landing page. App source lives in the version branches above.
