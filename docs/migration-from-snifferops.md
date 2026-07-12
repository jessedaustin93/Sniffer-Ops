# Migration From SnifferOps

Ethrox Detect was formerly developed under the SnifferOps codename.

This repository now uses the Ethrox Detect identity for current product names,
service names, packages, paths, launchers, artifacts, and documentation.
Historical commits are intentionally preserved.

## Compatibility Window

Linux currently accepts the old schema-1 LAN sync routes for compatibility with
unmigrated peers:

| Legacy endpoint | Current endpoint |
|---|---|
| `/snifferops/health` | `/ethrox-detect/health` |
| `/snifferops/awareness` | `/ethrox-detect/awareness` |
| `/snifferops/sync` | `/ethrox-detect/sync` |
| `/snifferops/sdr/deep-scan` | `/ethrox-detect/sdr/deep-scan` |
| `/snifferops/sdr/deep-scan/status` | `/ethrox-detect/sdr/deep-scan/status` |

Legacy routes return `deprecated_path: true` where practical. Removal should be
planned after Android, Windows, Linux, and appliance builds all publish
Ethrox Detect endpoint support.

## Local Data

The Linux migration script backs up old local state before moving data into the
Ethrox Detect layout. Backups are never deleted automatically.

Private captures, GPS history, databases, node IDs, trusted-device rules,
credentials, and local identifiers must stay out of Git.
