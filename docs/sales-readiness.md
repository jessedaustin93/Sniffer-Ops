# Ethrox Detect Sales Readiness

This document separates the current working prototype state from the work still
required before Ethrox Detect can ship as a customer appliance.

## Current Prototype Capability

The Raspberry Pi Zero 2 W keep-prototype can:

- boot headlessly into Ethrox Detect;
- start `ethrox-detect.service` automatically;
- scan Wi-Fi and onboard Bluetooth;
- expose the Ethrox Detect API on port `8766`;
- connect over Wi-Fi on the `AUSTIN` network;
- provide USB Ethernet rescue access at `192.168.7.2`;
- keep a stable USB gadget identity for the host interface;
- use key-only SSH with password SSH disabled;
- preserve a stable node identity across reboots;
- pass appliance self-test with only the expected no-RTL-SDR warning;
- ingest the T5810B hub awareness snapshot for prototype comparison.

Validated prototype version:

```text
Ethrox Detect 0.2.0-rc.1+1
```

## Not Sales Ready Yet

The prototype is useful for overnight field-style testing, but it is not ready
to sell. Required work:

- rebuild and flash a clean image from the current appliance branch instead of
  relying on live repairs;
- validate read-only-root behavior and dirty power loss recovery;
- attach and validate RTL-SDR hardware;
- create a repeatable manufacturing/provisioning flow;
- provide customer-safe Wi-Fi setup or pairing;
- finalize enclosure, cable strain relief, power supply, thermals, and labeling;
- complete privacy/security review and customer-facing legal wording;
- define update, rollback, and recovery procedures;
- produce signed/checksummed release artifacts and release notes;
- formalize a QC checklist for every unit.

## Sales-Unit Acceptance Checklist

A sales unit should not ship unless it passes:

- clean first boot from a freshly flashed image;
- Wi-Fi setup and reconnect after reboot;
- USB rescue route;
- API health and version endpoints;
- Wi-Fi scanner startup;
- Bluetooth scanner startup;
- RTL-SDR scanner startup when hardware is included;
- overnight scan run without failed services;
- dirty power-loss sample set;
- no private data or lab credentials in image artifacts;
- correct product version and build metadata;
- documented rollback/recovery route.

## Current Major Blockers

- T5810B `POST /ethrox-detect/sync` times out and needs hub-side debugging
  before reliable push-to-hub sync can be claimed.
- The Pi image must be rebuilt and reflashed from source after the latest
  appliance fixes.
- RTL-SDR has not been attached to the Pi prototype yet.
- Power-only overnight run has been started, but results need review after the
  run completes.
