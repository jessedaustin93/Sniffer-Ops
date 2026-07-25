import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from map_placement import compute_placements


def _profile(pid, name="dev", ptype="WIFI", est_lat=None, est_lon=None):
    return {
        "id": pid, "name": name, "type": ptype,
        "estimated_latitude": est_lat, "estimated_longitude": est_lon,
    }


def test_gps_tier_collapses_nearby_fixes_into_one_marker():
    profiles = [_profile("p1")]
    sightings = [
        {"device_id": "p1", "node_id": "hub", "captured_at": 1_000,
         "latitude": 10.0, "longitude": 20.0, "signal_strength": -40},
        {"device_id": "p1", "node_id": "hub", "captured_at": 2_000,
         "latitude": 10.0001, "longitude": 20.0001, "signal_strength": -35},
    ]
    markers, unplaced = compute_placements(profiles, sightings)
    assert unplaced == 0
    assert len(markers) == 1
    assert markers[0].tier == "gps"
    assert markers[0].count == 2


def test_linked_tier_places_non_gps_device_via_scanning_node_fix():
    profiles = [_profile("phone-no-gps", ptype="BLUETOOTH"), _profile("hub-self")]
    sightings = [
        # hub-self carries the scanning node's own GPS fix.
        {"device_id": "hub-self", "node_id": "hub", "captured_at": 1_000,
         "latitude": 40.0, "longitude": -70.0, "signal_strength": None},
        # phone-no-gps was sniffed by "hub" at the same moment, no GPS of its own.
        {"device_id": "phone-no-gps", "node_id": "hub", "captured_at": 1_000,
         "latitude": None, "longitude": None, "signal_strength": -55},
    ]
    markers, unplaced = compute_placements(profiles, sightings)
    assert unplaced == 0
    by_id = {m.profile_id: m for m in markers}
    assert by_id["phone-no-gps"].tier == "linked"
    assert by_id["phone-no-gps"].lat == 40.0
    assert by_id["phone-no-gps"].lon == -70.0


def test_anchor_tier_weights_toward_the_most_recent_node_fix():
    profiles = [_profile("phone-no-gps", ptype="BLUETOOTH"), _profile("hub-self")]
    sightings = [
        # Two GPS fixes for the scanning node, far apart in time and space.
        {"device_id": "hub-self", "node_id": "hub", "captured_at": 0,
         "latitude": 0.0, "longitude": 0.0, "signal_strength": None},
        {"device_id": "hub-self", "node_id": "hub", "captured_at": 100_000_000,
         "latitude": 10.0, "longitude": 10.0, "signal_strength": None},
        # Sighting is far outside the 20-minute link window of either fix,
        # but much closer in time to the second (recent) one.
        {"device_id": "phone-no-gps", "node_id": "hub", "captured_at": 95_000_000,
         "latitude": None, "longitude": None, "signal_strength": -60},
    ]
    markers, unplaced = compute_placements(profiles, sightings)
    assert unplaced == 0
    marker = next(m for m in markers if m.profile_id == "phone-no-gps")
    assert marker.tier == "anchor"
    # A flat average of the two fixes would land at (5.0, 5.0); recency
    # weighting should pull the result much closer to the recent (10, 10) fix.
    assert marker.lat > 5.0
    assert marker.lon > 5.0


def test_profile_with_no_sightings_falls_back_to_stored_estimate():
    profiles = [_profile("p1", est_lat=1.5, est_lon=2.5)]
    markers, unplaced = compute_placements(profiles, [])
    assert unplaced == 0
    assert markers[0].tier == "anchor"
    assert (markers[0].lat, markers[0].lon) == (1.5, 2.5)


def test_profile_with_no_placement_data_is_unplaced():
    profiles = [_profile("p1")]
    sightings = [
        {"device_id": "p1", "node_id": "unseen-node", "captured_at": 1_000,
         "latitude": None, "longitude": None, "signal_strength": -70},
    ]
    markers, unplaced = compute_placements(profiles, sightings)
    assert markers == []
    assert unplaced == 1
