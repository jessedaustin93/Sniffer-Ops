# Ethrox Detect — shared signature database

`flock-signatures.json` is the canonical, cross-platform detection database for
surveillance/RF infrastructure, seeded with the public **Flock Safety** set. It
is provider-neutral of any one tier: the ESP32 firmware
(`ethrox-detect-esp32`) loads it directly, and the Python/GTK and Windows
classifiers should grow a MAC-level matcher that consumes the same file.

## What it carries

- `wifi.oui[]` — Flock MAC OUI prefixes with **source** + **confidence** per
  entry. Includes the 30 curated flock-you (NitekryDPaul) prefixes, Flock's own
  IEEE registration `b4:1e:52`, and the locally-administered `82:6b:f2`.
- `wifi.ssid_keywords[]` — SSID/name substrings (case-insensitive).
- `wifi.ie_fingerprints[]` — the `wildcard-probe` fingerprint (probe request with
  an empty SSID IE, tag 0 length 0 — the Flock "phone-home" pattern).
- `ble.manufacturer_ids[]` / `ble.name_keywords[]` — BLE advertisement signals
  (e.g. company id `0x09C8`, names `flock`/`raven`).

## False-positive discipline

Entries flagged `requires_corroboration` sit on shared vendor ranges and must be
backed by the wildcard-probe fingerprint or an SSID/name clue before they are
treated as high confidence:

- `a4:cf:12`, `3c:71:bf` — **Espressif** OUIs (match any ESP32/ESP8266).
- `e4:aa:ea` — **Liteon** contract-manufacturer OUI.
- `82:6b:f2` — locally-administered/observed (`laa: true`).

## Relationship to the keyword classifier

The existing `linux/signal_signatures.py` +
`linux/classifier_rules/surveillance.json` are **metadata/keyword**-based
(SSID / name / vendor). They carry no MAC-level data. This file is the OUI/IE
layer; keep the two reconciled — a name/keyword hit and an OUI hit on the same
device is the strongest signal.

## Reconcile & grow

Reconcile against public sources (flock-you and forks, IEEE registrations,
DeFlock), integrate new prefixes with `source` + `confidence`, bump `version`,
append to `sources[]`, and push back so every tier inherits the improvement.
The ESP32 firmware treats its `data/signatures.json` as the working copy of this
file; changes here should be mirrored there (and vice-versa) until a single
publishing path is set up.
