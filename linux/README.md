# SnifferOps Linux Hub

Linux is the primary SnifferOps awareness hub for the Dell Precision T5810B. It is the local-first persistence, classification, correlation, mapping, and sync authority for the current architecture. Android is the mobile detector, and Windows is the secondary companion/RTL-SDR host.

SnifferOps is passive defensive awareness software. It stores local observations, preserves evidence, explains inferences, and supports lawful situational awareness. It does not attack equipment, inject packets, capture credentials, exploit devices, interfere with police, or support pursuit/traffic-stop/checkpoint evasion.

## Architecture

The Linux hub has four layers:

1. Raw scanner facts: Wi-Fi, Bluetooth/BLE, SDR, synchronized peer payloads, timestamps, signal strength, optional GPS, node identity, and legacy JSON migration input.
2. Durable SQLite storage: `signal_profiles` and bounded per-profile/per-node `signal_sightings`, WAL mode, stable signal profile IDs, stable sighting UUIDs, sync acknowledgments, and confirmed compaction.
3. Linux inference layer: versioned structured classifications, evidence rows, policy dispositions, ownership records, movement sessions, network-integrity models, cellular baselines/anomalies, derived entities, watch zones, enforcement locations, and route-exposure scoring foundation.
4. Interfaces: GTK4 tactical UI, read-only web dashboard, offline awareness map, Tailscale peer discovery, HTTP sync endpoints, GNOME autostart, and systemd user startup.

Existing Android and Windows schema-1 payloads still ingest. New Linux-generated structures are hub-local unless a future protocol version explicitly negotiates support.

## Install

```bash
git clone https://github.com/jessedaustin93/Sniffer-Ops
cd Sniffer-Ops
git checkout codex/linux-companion
cd linux
bash install.sh
```

`install.sh` installs GTK4/libadwaita, BlueZ, NetworkManager, optional RTL-SDR tools, the bundled fonts, icon, GNOME desktop launcher, GNOME autostart entry, `snifferops` command, and `~/.config/systemd/user/snifferops.service`.

## Launch And Startup

```bash
snifferops
python3 /path/to/Sniffer-Ops/linux/snifferops_gui.py
systemctl --user status snifferops
systemctl --user restart snifferops
```

The app binds the awareness API to `0.0.0.0:8766` by default and registers the D-Bus name `com.snifferops.linux` so duplicate launches do not create competing GUI instances.

GNOME autostart:

```bash
~/.config/autostart/com.snifferops.linux.desktop
```

Systemd user service:

```bash
~/.config/systemd/user/snifferops.service
```

## Data Location

| Path | Contents |
|---|---|
| `~/.snifferops/awareness.db` | Primary SQLite/WAL database |
| `~/.snifferops/awareness.json` | Legacy JSON migration source, kept for compatibility |
| `~/.snifferops/config.json` | Scanner toggles, sync port, peers, map defaults |
| `~/.snifferops/node_id` | Stable Linux node identity |
| `~/.snifferops/trusted_devices.json` | Private local trust overrides; do not commit |
| `~/.snifferops/network-captures/` | Optional local rotating packet summaries, not part of sync |

Back up before migration or deployment:

```bash
mkdir -p ~/.snifferops/backups
cp -a ~/.snifferops/awareness.db ~/.snifferops/backups/awareness.db.$(date -u +%Y%m%dT%H%M%SZ)
cp -a ~/.snifferops/awareness.db-wal ~/.snifferops/backups/ 2>/dev/null || true
cp -a ~/.snifferops/awareness.db-shm ~/.snifferops/backups/ 2>/dev/null || true
```

## Schema Migrations

SQLite is initialized in WAL mode with foreign keys enabled. `schema_migrations` records additive migration versions.

Current migration:

| Version | Name | Purpose |
|---|---|---|
| 1 | `linux_hub_inference_layer` | Adds classifier versions, structured classifications, evidence, ownership records, movement sessions, network-integrity tables, cellular baselines/anomalies, derived entities, watch/surveillance zones, enforcement locations, manual confirmations, dismissed findings, and policy profiles |
| 2 | `android_mobile_detector_sighting_metadata` | Adds optional per-sighting movement-session ID, speed, bearing, location provider, and source-node fields for Android mobile-detector sync |

Migration 1 does not delete or rewrite raw `signal_profiles` or `signal_sightings`. Removing a classification, zone, or derived entity must never delete raw source observations.

## Sync Compatibility

Linux keeps the existing schema-1 awareness endpoints:

| Endpoint | Method | Use |
|---|---|---|
| `/snifferops/health` | GET | Peer health and node identity |
| `/snifferops/awareness` | GET | Merged awareness state |
| `/snifferops/sync` | POST | Merge peer snapshot and return local snapshot |
| `/snifferops/sdr/deep-scan` | POST | Existing SDR deep-scan compatibility |
| `/snifferops/sdr/deep-scan/status` | GET | Existing SDR status compatibility |

Linux still accepts old Android and Windows payloads with missing richer metadata. Android protocol-version-2 payloads may include `nodeRole: mobile_detector`, capability metadata, node location, movement-session IDs, BLE advertisement notes, and per-sighting speed/bearing/location-provider fields. Missing fields degrade gracefully: partial observations are retained, unknown values stay unknown, and classifiers avoid false certainty.

## Classifier Architecture

The Linux inference layer separates:

- raw observed facts;
- inferred identity;
- identity confidence;
- user policy disposition;
- alert priority;
- supporting evidence;
- recommended defensive action.

Example:

| Field | Value |
|---|---|
| identity label | `Likely Flock Safety / ALPR camera` |
| family | `surveillance.flock` |
| confidence | `HIGH` |
| priority | `HIGH` |
| policyDisposition | `HOSTILE` |
| policyReason | `User policy marks positively identified Flock infrastructure hostile.` |

Confidence levels: `LOW`, `MEDIUM`, `HIGH`, `CONFIRMED`.

Priority levels: `INFO`, `WATCH`, `CAUTION`, `HIGH`, `CRITICAL`.

Policy dispositions are configurable and distinct from identity confidence. The default Linux policy marks positively identified Flock and strongly matched ALPR infrastructure `HOSTILE`. Public-safety vehicle and enforcement-location findings default to calm informational/watch behavior.

Rules live in `linux/classifier_rules/` with `linux/classifier_rules.json` kept as a compatibility fallback. Code defaults in `inference_engine.py` keep the system running if a rule file is missing or malformed. Every stored classification records the classifier version and the rules directory.

Current rule files:

```text
linux/classifier_rules/
  surveillance.json
  tracking.json
  network_integrity.json
  cellular.json
  public_safety.json
  route_exposure.json
  external_sources.json
```

Implemented classifier families:

```text
surveillance.infrastructure
surveillance.alpr
surveillance.flock
surveillance.camera
surveillance.mobile_camera
surveillance.unknown_roadside
tracking.ble
tracking.known_tracker
tracking.following
tracking.owned
tracking.unknown_companion
network.evil_twin
network.deauthentication
network.arp_spoofing
network.dns_hijack
network.gateway_change
network.dhcp_change
network.captive_portal_anomaly
network.encryption_downgrade
cellular.anomaly
cellular.possible_rogue_cell
cellular.downgrade
public_safety.vehicle_cluster
public_safety.possible_cruiser
public_safety.probable_cruiser
public_safety.confirmed_cruiser
public_safety.enforcement_location
public_safety.recurring_enforcement_location
surveillance.license_plate_reader.generic
surveillance.flock.fixed
surveillance.flock.mobile
surveillance.speed_camera
surveillance.red_light_camera
surveillance.traffic_camera
surveillance.camera_trailer
surveillance.roadside_sensor_cluster
surveillance.fusus
surveillance.axon
surveillance.genetec
surveillance.vigilant
surveillance.motorola_solutions
tracking.apple_findmy
tracking.apple_airtag
tracking.samsung_smarttag
tracking.tile
tracking.chipolo
tracking.ble_beacon
tracking.rotating_ble_identity
tracking.stationary_beacon
tracking.crowded_place_encounter
tracking.separated_after_encounter
network.ssid_clone
network.bssid_spoof
network.gateway_mac_change
network.gateway_ip_change
network.dns_server_change
network.dhcp_server_change
network.arp_gateway_conflict
network.suspicious_captive_portal
network.auto_join_risk
network.trusted_router_verified
cellular.unusual_cell
cellular.unseen_cell_at_known_location
cellular.stationary_cell_change
cellular.technology_downgrade
cellular.strong_unknown_cell
cellular.mcc_mnc_change
cellular.registration_failure_cluster
cellular.neighbor_environment_shift
entity.mobile_cluster
entity.fixed_infrastructure
entity.vehicle_equipment_package
entity.possible_rotated_identity
entity.probable_rotated_identity
entity.rejected_member
entity.confirmed_member
public_safety.work_vehicle_cluster
public_safety.fleet_vehicle_cluster
public_safety.bodycam_vendor_clue
public_safety.mdt_vendor_clue
public_safety.dashcam_vendor_clue
public_safety.alpr_vehicle_equipment
public_safety.stationary_roadside_observation
```

## Ownership Controls

Linux supports durable ownership states:

```text
Mine, Family, Trusted, Known neighbor, Unknown, Watch, Hostile, Ignore, False positive
```

Ownership and trust are not identity. Marking a tracker `Mine` or `Trusted` suppresses personal-tracking alerts but keeps sightings and evidence.

Private pattern-based trust remains in `~/.snifferops/trusted_devices.json`; durable manual ownership records are stored in `ownership_records`.

## GTK4 Interface

The GTK app keeps the existing tactical visual style and adds structured lenses:

- Priority Alerts
- Surveillance
- Personal Tracking
- Network Integrity
- Cellular
- Entities & Zones
- Wi-Fi
- Bluetooth
- SDR Radio
- Peers
- Settings
- Map

Finding rows show label, family, priority, confidence, disposition, evidence summary, observation count, source nodes, and recommended action. Actions are backed by SQLite state:

- Mine
- Family
- Trusted
- Watch
- Hostile
- Ignore
- False positive
- Dismiss
- Confirm tracker
- Confirm surveillance
- Confirm cruiser

Manual surveillance and cruiser confirmations require an extra confirmation dialog because those labels can misidentify vehicles or public-safety entities.

## Personal Tracking

Linux detects known or probable tracker-like BLE devices from names, manufacturer/service clues where present, repeated observations, node count, location availability, ownership state, and later movement-session context.

Current following-risk behavior:

- increases for AirTag/Find My, Samsung SmartTag, Tile, Chipolo, generic tracker/tag/beacon names;
- increases with repeated observations and multiple user-associated nodes;
- increases when the signal has repeated location-bearing observations;
- suppresses for `Mine`, `Family`, `Trusted`, `Ignore`, and `False positive`;
- never calls a single tracker sighting a following device.

States represented through families and labels include tracker nearby, known tracker, unknown companion, device under observation, possible/probable following tracker, owned tracker, family/trusted device, and dismissed false positive.

## Movement Sessions

Migration 1 adds `movement_sessions` and `movement_session_observations`. The current scoring foundation can work with incomplete GPS and bounded sightings. Future work should populate sessions from journey windows, GPS deltas, node identity, activity transitions, and co-travel timing.

## Network Integrity

Network Integrity is defensive and only for networks the user owns or is authorized to inspect.

Trusted fingerprints can include SSID, expected BSSID set, vendor, security mode, gateway IP/MAC, DHCP server, DNS servers, captive-portal expectation, normal channels/encryption, trusted location, and notes.

Implemented comparison behavior detects:

- trusted SSID with unexpected BSSID;
- duplicate SSIDs visible simultaneously;
- gateway IP or MAC change;
- DNS change;
- DHCP server change;
- encryption downgrade;
- unexpected captive portal.

Recommended actions are defensive: disconnect, disable auto-join, use mobile data, verify router/gateway/DNS, and mark changed hardware trusted only after verification.

## Cellular Anomalies

Linux stores cellular baseline/anomaly tables and includes cautious scoring helpers for synchronized collector metadata.

The scorer treats one indicator as low-confidence. Multiple indicators are required for elevated labels such as `possible rogue or misconfigured cell`.

Supported indicators include LTE/5G downgrade, unexpected GSM/older fallback, serving-cell change while stationary, MCC/MNC changes, and repeated registration failures.

Limitations are explicit: no single anomaly proves an IMSI catcher, and current Android/Windows collectors may not yet provide the needed cellular fields.

## Derived Entities And Public Safety

Migration 1 adds reversible derived entity tables for grouping signals likely belonging to the same physical equipment package, vehicle, or moving object. Source signals and sightings are never deleted by entity changes.

The public-safety foundation uses gradual labels:

- unknown mobile cluster;
- fleet or work-vehicle cluster;
- possible public-safety vehicle;
- probable law-enforcement cruiser;
- user-confirmed cruiser.

Default public-safety disposition is informational/watch, not hostile. Enforcement-location wording should remain calm: “Recurring enforcement position ahead. Check speed and drive legally.” The system must not become active pursuit, stop, checkpoint, or detention evasion tooling.

## Surveillance Zones

The schema supports persistent surveillance/watch zones with classification, confidence, observation count, first/last seen, center point, confidence/effective radius, freshness, policy disposition, route-impact weight, manual status, and false-positive state.

Do not infer camera field of view without sufficient evidence or manual confirmation.

### DeFlock And OpenStreetMap References

`classifier_rules/external_sources.json` describes DeFlock and OpenStreetMap as optional public reference sources for ALPR/Flock evidence. Linux does not automatically fetch these sources. A future explicit import tool may use DeFlock/OSM tags such as `surveillance:type=ALPR`, `camera:type=ALPR`, and `manufacturer=Flock Safety` as evidence for watch-zone seeds or classification recalculation.

Imported public-map references should remain separate from raw scanner facts and should preserve attribution/licensing requirements. Crowdsourced references can raise confidence but should not be treated as user confirmation unless Jesse manually confirms the location or device.

## Route Exposure Scoring

`inference_engine.route_exposure_score()` is a reusable Linux-side foundation for future route segment scoring. It can score supplied route points against local findings using family weights, confidence, distance decay, and conceptual profiles:

- Fastest
- Balanced
- Low Exposure
- Maximum Privacy

This is not navigation software and does not perform active police-evasion routing.

## Testing

Run the Linux tests:

```bash
cd /home/jesse/Sniffer-Ops
pytest -q linux/tests
```

Synthetic coverage includes migration creation, classifier version recording, confidence/priority/disposition separation, evidence preservation, ownership suppression, tracker-following scoring, old Android/Windows payload ingestion, network integrity comparisons, cautious cellular anomaly scoring, and route exposure scoring.

## Privacy And Legal Boundaries

- Keep processing local-first.
- Do not commit runtime databases, logs, captures, map tiles, GPS history, secrets, private SSIDs, MAC allowlists, or personal identifiers.
- Keep published default coordinates generic.
- Preserve raw evidence for recalculation.
- Use SnifferOps for passive awareness and defensive inspection only.
- Public-safety alerts should advise lawful driving, not evasion.

## Android Mobile Detector Fields

Android now sends the first Linux-hub mobile-detector fields while preserving current payload compatibility:

- stable collector protocol version and capability list;
- detection-time GPS with accuracy, speed, heading, and movement/session ID where Android exposes them;
- BLE manufacturer data, service UUIDs, advertised service data, Tx power, connectability, and advertised names through notes;
- `nodeRole: mobile_detector`;

Future Android upgrades should add:

- altitude, richer activity/motion state, and explicit journey boundaries;
- BLE address type, rotating-address hints, and fuller scan response fields;
- Wi-Fi BSSID vendor/OUI, security mode, channel width, frequency, capabilities, information elements where Android permits;
- cellular radio technology, serving cell ID, neighboring cells, MCC, MNC, TAC/LAC, PCI, ARFCN/EARFCN/NRARFCN, signal levels, registration failures, network transitions, and stationary/moving state;
- user-associated node identity and collection context;
- ownership/trust hints from local user actions without forcing Linux policy;
- optional movement-session boundaries and crowded-location hints.

## Future Windows Companion Upgrade

Windows should later add:

- protocol version/capabilities for guarded richer sync;
- Wi-Fi BSSID/vendor/security/channel-width/encryption details;
- gateway IP/MAC, DNS, DHCP, captive-portal observations for authorized networks;
- BLE manufacturer/service data where supported by adapter APIs;
- SDR observation metadata with scanner settings, bin width, noise floor, peak prominence, and hardware source;
- packet-summary-derived defensive network facts without credentials or payload capture;
- movement/session IDs when acting as a mobile or vehicle-associated collector;
- manual ownership/trust UI that sends optional hints but does not override Linux policy.

Linux is ready to accept these optional fields as raw profile/sighting metadata, classifier evidence, network fingerprints, cellular baselines, movement sessions, and derived-entity inputs. Current collectors can omit them safely.
