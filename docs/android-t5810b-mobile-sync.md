# Android T5810B Mobile Sync Notes

Date: 2026-07-26

These notes describe the sanitized Android update for Ethrox Detect. They intentionally omit private hub addresses, node identifiers, MAC addresses, GPS trails, raw scan logs, and device serials.

## Current Direction

- The Android app remains installed under the historical SnifferOps package ID so existing devices upgrade in place.
- User-facing branding is Ethrox Detect.
- The phone is a mobile detector and local journal.
- The T5810B is the primary awareness, persistence, classification, and correlation hub.
- Other computers are companion machines, not hub targets.

## Mobile App Behavior

- Fresh installs default hub sync to enabled and expect the operator to configure the private T5810B endpoint locally.
- The Hub Sync screen sends stored sightings to the T5810B hub and unlocks compaction only after the hub confirms exact sighting IDs.
- Failed or interrupted sync attempts leave phone history intact.
- Wi-Fi, Bluetooth, BLE, NFC, and cellular remain the active phone-side sensing paths.
- Phone-side SDR controls, USB SDR permission handling, network SDR mode, and deep-scan client calls were removed from the Android app.

## Classification Update

- Flock Safety-style detection uses a sanitized Android asset copy of the shared Ethrox Detect Flock signature set and names high-confidence matches as Flock Safety infrastructure.
- Lower-confidence Flock-related OUIs remain suspicious until corroborated by names, context, or hub-side history.
- Common wireless assessment and hostile-tool labels are loaded from a sanitized Android asset so suspicious SSIDs, Bluetooth names, or BLE metadata are surfaced as alert-worthy assessment-tool signals.
- Android does not expose raw 802.11 management frames to normal apps, so phone-side deauth detection means visible deauth-tool classification rather than packet-level deauthentication-frame detection.

## Phone Workload Guardrails

- Wi-Fi scan requests are rate-limited more conservatively.
- Live state refresh and database persistence are batched to reduce UI, storage, and radio pressure.
- The app still records durable evidence locally, but high-rate callback bursts are coalesced before writes.

## Verification Summary

- Android debug build completed successfully.
- Upgrade install over the existing SnifferOps package completed successfully.
- The launched app showed Ethrox Detect branding and no SDR dashboard controls.
- Hub sync completed successfully against the configured T5810B endpoint and returned confirmed sighting acknowledgements.
- The installed app loaded sanitized Android signature assets at startup.
- A send-and-compact cycle completed without the previous UI freeze after compaction was moved into a quieter, bounded path.

## Deauth Classification Boundary

The Android app can classify visible deauth-related tooling when names or BLE
metadata match the signature pack. It cannot claim packet-level deauthentication
frame detection because normal Android app APIs do not expose raw 802.11
management frames. Packet-level deauth detection belongs on approved raw-radio,
firmware, or hub-side capture paths that can inspect those frames directly.

## Sanitization Rules

Keep the following out of public notes, issues, and commits:

- Private Tailscale addresses or MagicDNS names
- GPS coordinates, movement tracks, and raw capture logs
- MAC addresses, serial numbers, Android IDs, node IDs, and trusted-device rules
- Secrets, credentials, API keys, tokens, and local database files
