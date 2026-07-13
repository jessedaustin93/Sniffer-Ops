# Keep Prototype Overnight Test

This is the operating plan for the Raspberry Pi Zero 2 W keep-prototype.

## Device Identity

- Hostname: `ethrox-detect-fffd49`
- Product version: `0.2.0-rc.1+1`
- Node ID: `fffd4900c67f4408`
- Wi-Fi IP during setup: `192.168.50.210`
- USB rescue IP: `192.168.7.2`
- T5810B hub: `192.168.50.179:8766`

## Current Configuration

The Pi is configured to start Ethrox Detect from systemd with the T5810B hub as
a prototype peer:

```text
/opt/ethrox-detect/venv/bin/python /opt/ethrox-detect/ethrox_detect_linux.py --peer 192.168.50.179:8766:t5810b-hub --plain
```

`/var/lib/ethrox-detect/config.json` also records the same peer for future
configuration-aware service startup.

## Power-Only Run

Goal: prove the Pi can run as a headless Ethrox Detect node from wall power,
without being attached to a computer over USB.

Before placing it:

1. Confirm `ethrox-detect.service` is active.
2. Confirm Wi-Fi is connected.
3. Confirm API health works over Wi-Fi.
4. Confirm the overnight sample timer is active.
5. Move power from USB-computer connection to a stable wall power source.

Validation commands:

```bash
curl -fsS http://192.168.50.210:8766/ethrox-detect/health
curl -fsS http://192.168.50.210:8766/ethrox-detect/web/status
ssh jesse@192.168.50.210 'systemctl is-active ethrox-detect.service'
ssh jesse@192.168.50.210 'systemctl list-timers ethrox-detect-overnight-sample.timer'
```

## Overnight Logging

The prototype writes five-minute health samples to:

```text
/var/lib/ethrox-detect/overnight/YYYYMMDD-power-only.jsonl
```

Each sample records:

- timestamp;
- hostname;
- service state;
- failed systemd units;
- Wi-Fi address;
- USB address if connected;
- local API health;
- local profile/type/class counts;
- T5810B hub health.

## T5810B Sync Status

The Pi can reach the T5810B health and version endpoints. It also ingested the
hub awareness snapshot during setup, so the Pi has the hub's current awareness
set for local comparison.

Known limitation:

- `POST http://192.168.50.179:8766/ethrox-detect/sync` times out with no
  response.

Because of that, reliable push-to-hub sync is not yet proven. For this overnight
run, success means:

- the Pi keeps scanning;
- the API stays up;
- Wi-Fi stays connected;
- the hub remains reachable;
- the local profile counts continue to update;
- there are no failed units.

Tomorrow's RTL-SDR run should repeat the same test after attaching the SDR and
restarting the service.
