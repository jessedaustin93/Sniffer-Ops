# Changelog

All notable changes to Ethrox Detect are documented here.

## Unreleased

### Fixed

- **Linux hub: awareness map placement correctness.** The map's "linked"
  placement tier — which places a non-GPS-capable device near the scanning
  node's own GPS position at the time it was seen — was unreachable due to
  a query that excluded non-GPS sightings before they ever reached the
  placement logic. Non-GPS devices always fell back to a stored/estimated
  position instead of a live one. Fixed the query, and made the fallback
  "anchor" tier use a recency-weighted position instead of a flat average
  across historical fixes, so stale fixes no longer pull a device's marker
  toward a location it hasn't been near recently.
- Added the first automated test coverage for the map placement engine,
  covering all placement tiers.

### Known follow-up

- The map still renders one marker per raw signal profile rather than one
  per consolidated physical entity (e.g. a phone, laptop, and watch carried
  by the same person). Correlating placements through the existing
  multi-signal entity model is tracked as separate follow-up work.
