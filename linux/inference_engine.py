"""
Linux hub inference engine for SnifferOps.

This module keeps raw observations separate from inferred identity, policy
disposition, alert priority, and supporting evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
import re
import time
import uuid
from typing import Any

import db
import signal_signatures


ENGINE_VERSION = "linux-inference-1.0.0"

PRIORITIES = ("INFO", "WATCH", "CAUTION", "HIGH", "CRITICAL")
CONFIDENCE = ("LOW", "MEDIUM", "HIGH", "CONFIRMED")
OWNERSHIP_STATES = (
    "Mine", "Family", "Trusted", "Known neighbor", "Unknown",
    "Watch", "Hostile", "Ignore", "False positive",
)

CLASSIFIER_FAMILIES = (
    "surveillance.infrastructure",
    "surveillance.alpr",
    "surveillance.license_plate_reader.generic",
    "surveillance.flock",
    "surveillance.flock.fixed",
    "surveillance.flock.mobile",
    "surveillance.camera",
    "surveillance.speed_camera",
    "surveillance.red_light_camera",
    "surveillance.traffic_camera",
    "surveillance.camera_trailer",
    "surveillance.roadside_sensor_cluster",
    "surveillance.mobile_camera",
    "surveillance.unknown_roadside",
    "surveillance.fusus",
    "surveillance.axon",
    "surveillance.genetec",
    "surveillance.vigilant",
    "surveillance.motorola_solutions",
    "tracking.ble",
    "tracking.apple_findmy",
    "tracking.apple_airtag",
    "tracking.samsung_smarttag",
    "tracking.tile",
    "tracking.chipolo",
    "tracking.ble_beacon",
    "tracking.rotating_ble_identity",
    "tracking.stationary_beacon",
    "tracking.crowded_place_encounter",
    "tracking.separated_after_encounter",
    "tracking.known_tracker",
    "tracking.following",
    "tracking.owned",
    "tracking.unknown_companion",
    "network.evil_twin",
    "network.ssid_clone",
    "network.bssid_spoof",
    "network.deauthentication",
    "network.arp_spoofing",
    "network.dns_hijack",
    "network.dns_server_change",
    "network.gateway_change",
    "network.gateway_mac_change",
    "network.gateway_ip_change",
    "network.dhcp_change",
    "network.dhcp_server_change",
    "network.arp_gateway_conflict",
    "network.captive_portal_anomaly",
    "network.suspicious_captive_portal",
    "network.encryption_downgrade",
    "network.auto_join_risk",
    "network.trusted_router_verified",
    "cellular.anomaly",
    "cellular.unusual_cell",
    "cellular.unseen_cell_at_known_location",
    "cellular.stationary_cell_change",
    "cellular.technology_downgrade",
    "cellular.strong_unknown_cell",
    "cellular.mcc_mnc_change",
    "cellular.registration_failure_cluster",
    "cellular.neighbor_environment_shift",
    "cellular.possible_rogue_cell",
    "cellular.downgrade",
    "entity.mobile_cluster",
    "entity.fixed_infrastructure",
    "entity.vehicle_equipment_package",
    "entity.possible_rotated_identity",
    "entity.probable_rotated_identity",
    "entity.rejected_member",
    "entity.confirmed_member",
    "public_safety.vehicle_cluster",
    "public_safety.work_vehicle_cluster",
    "public_safety.fleet_vehicle_cluster",
    "public_safety.bodycam_vendor_clue",
    "public_safety.mdt_vendor_clue",
    "public_safety.dashcam_vendor_clue",
    "public_safety.alpr_vehicle_equipment",
    "public_safety.stationary_roadside_observation",
    "public_safety.possible_cruiser",
    "public_safety.probable_cruiser",
    "public_safety.confirmed_cruiser",
    "public_safety.enforcement_location",
    "public_safety.recurring_enforcement_location",
)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_RULES_PATH = os.path.join(_BASE_DIR, "classifier_rules.json")
_RULES_DIR = os.path.join(_BASE_DIR, "classifier_rules")


@dataclass
class Evidence:
    type: str
    summary: str
    observed_at: int | None = None
    source_node: str | None = None
    signal_id: str | None = None
    weight: float = 1.0
    raw: dict[str, Any] = field(default_factory=dict)

    def as_db(self) -> dict:
        return {
            "id": uuid.uuid4().hex,
            "type": self.type,
            "summary": self.summary,
            "observed_at": self.observed_at,
            "source_node": self.source_node,
            "signal_id": self.signal_id,
            "weight": self.weight,
            "raw": self.raw,
        }


@dataclass
class Finding:
    family: str
    label: str
    priority: str
    confidence: str
    policy_disposition: str
    policy_reason: str
    recommended_next_step: str
    related_signal_ids: list[str]
    first_seen: int | None
    last_seen: int | None
    observation_count: int
    source_nodes: list[str]
    evidence: list[Evidence]
    related_entity_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    manual_status: str = "unreviewed"
    false_positive: bool = False
    dismissed: bool = False

    @property
    def id(self) -> str:
        subject = ",".join(sorted(self.related_signal_ids)) or self.related_entity_id or self.label
        return uuid.uuid5(uuid.NAMESPACE_URL, f"snifferops:{self.family}:{subject}").hex

    def as_record(self) -> dict:
        return {
            "id": self.id,
            "family": self.family,
            "classifier_version": ENGINE_VERSION,
            "label": self.label,
            "priority": self.priority,
            "confidence": self.confidence,
            "policy_disposition": self.policy_disposition,
            "policy_reason": self.policy_reason,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "observation_count": self.observation_count,
            "source_nodes": self.source_nodes,
            "related_signal_ids": self.related_signal_ids,
            "related_entity_id": self.related_entity_id,
            "recommended_next_step": self.recommended_next_step,
            "manual_status": self.manual_status,
            "false_positive": self.false_positive,
            "dismissed": self.dismissed,
            "recalculated_at": _now_ms(),
            "details": self.details,
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_rules() -> dict:
    defaults = {
        "version": ENGINE_VERSION,
        "following_thresholds": {
            "watch": 35,
            "possible": 55,
            "probable": 75,
        },
        "route_weights": {
            "surveillance.flock": 4.0,
            "surveillance.alpr": 4.0,
            "surveillance.camera": 1.8,
            "public_safety.enforcement_location": 1.4,
            "tracking.following": 3.0,
        },
    }
    try:
        with open(_RULES_PATH, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            defaults.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass
    if os.path.isdir(_RULES_DIR):
        for name in sorted(os.listdir(_RULES_DIR)):
            if not name.endswith(".json"):
                continue
            key = name[:-5]
            try:
                with open(os.path.join(_RULES_DIR, name), "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    defaults[key] = loaded
            except (OSError, json.JSONDecodeError):
                defaults.setdefault("malformed_rule_files", []).append(name)
    route_rules = defaults.get("route_exposure")
    if isinstance(route_rules, dict) and isinstance(route_rules.get("weights"), dict):
        defaults.setdefault("route_weights", {}).update(route_rules["weights"])
    return defaults


def record_classifier_versions() -> None:
    for family in CLASSIFIER_FAMILIES:
        db.upsert_classifier_version(family, ENGINE_VERSION, _RULES_DIR)


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _text(profile: dict) -> str:
    return " ".join(
        str(profile.get(k) or "")
        for k in ("name", "address", "manufacturer", "device_class", "type", "notes")
    ).lower()


def _rule_matches(rule: dict, text: str) -> bool:
    include = rule.get("patterns") or []
    require = rule.get("required_patterns") or []
    exclude = rule.get("exclude_patterns") or []
    if include and not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in include):
        return False
    if require and not all(re.search(pattern, text, flags=re.IGNORECASE) for pattern in require):
        return False
    if exclude and any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in exclude):
        return False
    return bool(include or require)


def _best_rule(domain_rules: dict, text: str) -> dict | None:
    matches = [
        rule for rule in domain_rules.get("definitions", [])
        if isinstance(rule, dict) and _rule_matches(rule, text)
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda r: (int(r.get("score", 0)), r.get("family", "")), reverse=True)[0]


def _confidence_from_signature(value: str) -> str:
    return {
        "confirmed": "CONFIRMED",
        "high": "HIGH",
        "medium": "MEDIUM",
        "low": "LOW",
    }.get(str(value).lower(), "LOW")


def _ownership_state(profile_id: str) -> str:
    record = db.get_ownership_state(profile_id)
    return str(record.get("state") or "Unknown") if record else "Unknown"


def _owned_or_suppressed(state: str) -> bool:
    return state in {"Mine", "Family", "Trusted", "Ignore", "False positive"}


def classify_profile(profile: dict) -> list[Finding]:
    """Classify one signal profile without modifying the raw profile."""
    record_classifier_versions()
    rules = _load_rules()
    profile_id = str(profile.get("id") or "")
    now = _now_ms()
    first_seen = profile.get("first_seen")
    last_seen = profile.get("last_seen")
    seen = int(profile.get("seen_count") or 0)
    source_nodes = _json_list(profile.get("node_ids"))
    state = _ownership_state(profile_id)
    signature = signal_signatures.classify_signal_signature({
        "name": profile.get("name"),
        "address": profile.get("address"),
        "manufacturer": profile.get("manufacturer"),
        "deviceClass": profile.get("device_class"),
        "type": profile.get("type"),
        "notes": profile.get("notes"),
    })
    evidence = [
        Evidence(
            "raw_profile",
            f"{profile.get('type') or 'UNKNOWN'} profile observed {seen} time(s)",
            observed_at=last_seen,
            signal_id=profile_id,
            raw={
                "name_present": bool(profile.get("name")),
                "address_present": bool(profile.get("address")),
                "manufacturer_present": bool(profile.get("manufacturer")),
            },
        )
    ]
    if state != "Unknown":
        evidence.append(Evidence("ownership", f"Ownership state: {state}", observed_at=now, signal_id=profile_id))

    findings: list[Finding] = []
    text = _text(profile)

    if signature.matched:
        evidence.append(Evidence("signature", signature.evidence_text(), observed_at=last_seen, signal_id=profile_id))
        family = "surveillance.infrastructure"
        disposition = "UNKNOWN"
        policy_reason = ""
        priority = "WATCH"
        label = signature.label
        confidence = _confidence_from_signature(signature.confidence)

        if signature.alert_keyword == "flock":
            family = "surveillance.flock"
            priority = "HIGH"
            disposition = "HOSTILE"
            policy_reason = "User policy marks positively identified Flock infrastructure hostile."
        elif signature.alert_keyword == "alpr":
            family = "surveillance.alpr"
            priority = "HIGH"
            disposition = "HOSTILE"
            policy_reason = "User policy marks strongly matched ALPR infrastructure hostile."
        elif signature.family in {"camera", "network-camera", "surveillance"}:
            family = "surveillance.camera" if signature.family != "surveillance" else "surveillance.infrastructure"
            disposition = "WATCH"
            priority = "CAUTION" if "traffic" in text or "speed" in text else "WATCH"
        elif signature.family == "tracker":
            family = "tracking.known_tracker"
            disposition = state if state != "Unknown" else "WATCH"
            priority = "INFO" if _owned_or_suppressed(state) else "WATCH"
        elif signature.family == "attack":
            if re.search(r"deauth|disassociation", text):
                family = "network.deauthentication"
                label = "Deauthentication or disassociation indicator"
            elif re.search(r"evil[-_\\s]*twin", text):
                family = "network.evil_twin"
                label = "Evil twin network indicator"
            priority = "CRITICAL"
            disposition = "HOSTILE"
            policy_reason = "Defensive network-integrity policy."
        elif signature.family == "drone":
            family = "surveillance.mobile_camera"
            disposition = "WATCH"
            priority = "WATCH"

        surveillance_rule = _best_rule(rules.get("surveillance", {}), text)
        if surveillance_rule and (
            family.startswith("surveillance.")
            or surveillance_rule.get("family", "").startswith("surveillance.")
        ):
            family = surveillance_rule.get("family", family)
            label = surveillance_rule.get("label", label)
            priority = surveillance_rule.get("priority", priority)
            confidence = surveillance_rule.get("confidence", confidence)
            disposition = surveillance_rule.get("policy_disposition", disposition)
            policy_reason = surveillance_rule.get("policy_reason", policy_reason)
            evidence.append(Evidence(
                "classifier_rule",
                surveillance_rule.get("evidence", f"Matched {family} classifier rule."),
                observed_at=last_seen,
                signal_id=profile_id,
                raw={"rule_id": surveillance_rule.get("id", "")},
            ))

        findings.append(Finding(
            family=family,
            label=label,
            priority=priority,
            confidence=confidence,
            policy_disposition=disposition,
            policy_reason=policy_reason,
            recommended_next_step=_recommendation_for_family(family),
            related_signal_ids=[profile_id],
            first_seen=first_seen,
            last_seen=last_seen,
            observation_count=seen,
            source_nodes=source_nodes,
            evidence=evidence.copy(),
            details={"signature_family": signature.family, "ownership_state": state},
        ))

    if (profile.get("type") or "").upper() in {"BLUETOOTH", "BLE"}:
        tracker = tracker_following_risk(profile, rules)
        tracker_rule = _best_rule(rules.get("tracking", {}), text)
        if tracker["score"] > 0:
            if _owned_or_suppressed(state):
                family = "tracking.owned"
                priority = "INFO"
                label = f"{state} BLE device"
                disposition = state
            elif tracker["score"] >= rules["following_thresholds"]["probable"]:
                family = "tracking.following"
                priority = "HIGH"
                label = "Probable following tracker"
                disposition = "WATCH"
            elif tracker["score"] >= rules["following_thresholds"]["possible"]:
                family = "tracking.following"
                priority = "CAUTION"
                label = "Possible following BLE device"
                disposition = "WATCH"
            elif tracker["score"] >= rules["following_thresholds"]["watch"]:
                family = "tracking.unknown_companion"
                priority = "WATCH"
                label = "Unknown companion device under observation"
                disposition = "WATCH"
            else:
                family = "tracking.ble"
                priority = "INFO"
                label = "BLE tracker-like device nearby"
                disposition = "UNKNOWN"
            if tracker_rule and not _owned_or_suppressed(state) and family != "tracking.following":
                family = tracker_rule.get("family", family)
                label = tracker_rule.get("label", label)
                priority = tracker_rule.get("priority", priority)

            tracker_evidence = evidence.copy()
            for reason in tracker["reasons"]:
                tracker_evidence.append(Evidence("following_score", reason, observed_at=last_seen, signal_id=profile_id))
            if tracker_rule:
                tracker_evidence.append(Evidence(
                    "classifier_rule",
                    tracker_rule.get("evidence", f"Matched {tracker_rule.get('family')} classifier rule."),
                    observed_at=last_seen,
                    signal_id=profile_id,
                    raw={"rule_id": tracker_rule.get("id", "")},
                ))
            findings.append(Finding(
                family=family,
                label=label,
                priority=priority,
                confidence=tracker["confidence"],
                policy_disposition=disposition,
                policy_reason="Ownership state suppresses tracking alerts." if _owned_or_suppressed(state) else "",
                recommended_next_step="Observe across movement sessions before treating as intentional tracking.",
                related_signal_ids=[profile_id],
                first_seen=first_seen,
                last_seen=last_seen,
                observation_count=seen,
                source_nodes=source_nodes,
                evidence=tracker_evidence,
                details={"following_risk_score": tracker["score"], "ownership_state": state},
            ))

    return findings


def tracker_following_risk(profile: dict, rules: dict | None = None) -> dict:
    rules = rules or _load_rules()
    profile_id = str(profile.get("id") or "")
    state = _ownership_state(profile_id)
    text = _text(profile)
    seen = int(profile.get("seen_count") or 0)
    nodes = _json_list(profile.get("node_ids"))
    has_location = profile.get("estimated_latitude") is not None and profile.get("estimated_longitude") is not None
    score = 0
    reasons: list[str] = []

    if re.search(r"airtag|find\\s*my|smarttag|tile|chipolo|tracker|tag|beacon", text):
        score += 35
        reasons.append("Metadata resembles a known BLE tracker family.")
    if seen >= 3:
        score += min(25, seen * 3)
        reasons.append(f"Repeated presence across {seen} observations.")
    if len(nodes) >= 2:
        score += 12
        reasons.append(f"Seen by {len(nodes)} collection nodes.")
    if has_location and seen >= 3:
        score += 12
        reasons.append("Has repeated observations with a location estimate.")
    if _owned_or_suppressed(state):
        score = max(0, score - 65)
        reasons.append(f"Suppressed by ownership state: {state}.")
    if state == "Watch":
        score += 15
        reasons.append("User marked this signal Watch.")
    if state == "Hostile":
        score += 30
        reasons.append("User marked this signal Hostile.")
    if seen <= 1:
        score = min(score, 30)
        reasons.append("Single sighting prevents following classification.")

    score = max(0, min(100, score))
    confidence = "LOW"
    if score >= rules["following_thresholds"]["probable"]:
        confidence = "HIGH"
    elif score >= rules["following_thresholds"]["possible"]:
        confidence = "MEDIUM"
    return {"score": score, "confidence": confidence, "reasons": reasons}


def recalculate_profile(profile_id: str) -> list[Finding]:
    profile = db.get_profile(profile_id)
    if not profile:
        return []
    findings = classify_profile(profile)
    for finding in findings:
        db.upsert_classification(finding.as_record(), [e.as_db() for e in finding.evidence])
    return findings


def recalculate_all() -> list[Finding]:
    all_findings: list[Finding] = []
    for profile in db.get_all_profiles():
        findings = classify_profile(profile)
        for finding in findings:
            db.upsert_classification(finding.as_record(), [e.as_db() for e in finding.evidence])
        all_findings.extend(findings)
    return all_findings


def compare_trusted_network(fingerprint: dict, observation: dict) -> list[Finding]:
    """Return defensive network-integrity findings for an authorized network."""
    now = int(observation.get("observed_at") or _now_ms())
    findings: list[Finding] = []
    ssid = observation.get("ssid") or fingerprint.get("ssid") or "trusted network"
    base = {
        "related_signal_ids": [],
        "first_seen": now,
        "last_seen": now,
        "observation_count": 1,
        "source_nodes": [observation.get("source_node")] if observation.get("source_node") else [],
        "policy_disposition": "WATCH",
        "policy_reason": "Defensive inspection of trusted or authorized network.",
    }

    def add(family: str, label: str, priority: str, confidence: str, ev: list[str], step: str) -> None:
        findings.append(Finding(
            family=family,
            label=label,
            priority=priority,
            confidence=confidence,
            recommended_next_step=step,
            evidence=[Evidence("network_integrity", item, observed_at=now, raw={"ssid": ssid}) for item in ev],
            details={"ssid": ssid},
            **base,
        ))

    expected_bssids = {str(v).lower() for v in fingerprint.get("bssid_set", [])}
    observed_bssid = str(observation.get("bssid") or "").lower()
    if expected_bssids and observed_bssid and observed_bssid not in expected_bssids:
        add("network.evil_twin", f"Trusted SSID {ssid} has unexpected BSSID", "HIGH", "HIGH",
            [f"Observed BSSID {observed_bssid} is not in trusted set."],
            "Disconnect, disable auto-join, and verify the router before trusting the AP.")
    if observation.get("duplicate_ssid_visible"):
        add("network.evil_twin", f"Duplicate SSID visible for {ssid}", "HIGH", "MEDIUM",
            ["Original trusted SSID appears duplicated nearby."],
            "Avoid joining until the duplicate AP is explained.")
    if fingerprint.get("gateway_ip") and observation.get("gateway_ip") and fingerprint["gateway_ip"] != observation["gateway_ip"]:
        add("network.gateway_change", f"Gateway IP changed on {ssid}", "CAUTION", "MEDIUM",
            [f"Expected gateway IP {fingerprint['gateway_ip']}; observed {observation['gateway_ip']}."],
            "Inspect router and DHCP configuration before marking the change trusted.")
    if fingerprint.get("gateway_mac") and observation.get("gateway_mac") and fingerprint["gateway_mac"].lower() != observation["gateway_mac"].lower():
        add("network.gateway_change", f"Gateway MAC changed on {ssid}", "HIGH", "HIGH",
            [f"Expected gateway MAC {fingerprint['gateway_mac']}; observed {observation['gateway_mac']}."],
            "Disconnect and verify the physical router or gateway.")
    if set(fingerprint.get("dns_servers") or []) and set(observation.get("dns_servers") or []) != set(fingerprint.get("dns_servers") or []):
        add("network.dns_hijack", f"DNS servers changed on {ssid}", "CAUTION", "MEDIUM",
            ["Observed DNS server set differs from trusted fingerprint."],
            "Inspect DNS/DHCP settings and use mobile data if the change is unexpected.")
    if fingerprint.get("dhcp_server") and observation.get("dhcp_server") and fingerprint["dhcp_server"] != observation["dhcp_server"]:
        add("network.dhcp_change", f"DHCP server changed on {ssid}", "CAUTION", "MEDIUM",
            [f"Expected DHCP {fingerprint['dhcp_server']}; observed {observation['dhcp_server']}."],
            "Verify the DHCP server before trusting this network.")
    if fingerprint.get("normal_encryption") and observation.get("encryption") and fingerprint["normal_encryption"].lower() != observation["encryption"].lower():
        add("network.encryption_downgrade", f"Encryption changed on {ssid}", "HIGH", "HIGH",
            [f"Expected {fingerprint['normal_encryption']}; observed {observation['encryption']}."],
            "Do not join if encryption is weaker than expected.")
    if not fingerprint.get("captive_portal_expected") and observation.get("captive_portal"):
        add("network.captive_portal_anomaly", f"Unexpected captive portal on {ssid}", "CAUTION", "MEDIUM",
            ["A captive portal appeared on a network fingerprinted as normal."],
            "Avoid entering credentials and verify the network path.")
    return findings


def score_cellular_anomaly(baseline: dict, observation: dict) -> Finding | None:
    indicators: list[str] = []
    now = int(observation.get("observed_at") or _now_ms())
    old_rat = str(baseline.get("radio_technology") or "").upper()
    new_rat = str(observation.get("radio_technology") or "").upper()
    if old_rat in {"LTE", "5G", "NR"} and new_rat in {"GSM", "EDGE", "UMTS"}:
        indicators.append(f"Radio technology downgraded from {old_rat} to {new_rat}.")
    if baseline.get("mcc") and observation.get("mcc") and baseline["mcc"] != observation["mcc"]:
        indicators.append("MCC changed from the local baseline.")
    if baseline.get("mnc") and observation.get("mnc") and baseline["mnc"] != observation["mnc"]:
        indicators.append("MNC changed from the local baseline.")
    if baseline.get("serving_cell_id") and observation.get("serving_cell_id") and baseline["serving_cell_id"] != observation["serving_cell_id"] and observation.get("stationary"):
        indicators.append("Serving cell changed while stationary.")
    if observation.get("registration_failures"):
        indicators.append("Repeated registration failures reported.")
    if not indicators:
        return None

    confidence = "LOW"
    priority = "WATCH"
    family = "cellular.anomaly"
    label = "Unusual cellular event"
    if len(indicators) >= 2:
        confidence = "MEDIUM"
        priority = "CAUTION"
        label = "Suspicious cellular pattern"
    if any("downgraded" in item for item in indicators):
        family = "cellular.downgrade"
        label = "Possible cellular downgrade"
    if len(indicators) >= 3:
        family = "cellular.possible_rogue_cell"
        label = "Possible rogue or misconfigured cell"
        confidence = "HIGH"

    return Finding(
        family=family,
        label=label,
        priority=priority,
        confidence=confidence,
        policy_disposition="WATCH",
        policy_reason="Cautious cellular anomaly policy; multiple indicators required for higher confidence.",
        recommended_next_step="Treat as a caution signal only; one anomaly is not proof of an IMSI catcher.",
        related_signal_ids=[],
        first_seen=now,
        last_seen=now,
        observation_count=1,
        source_nodes=[observation.get("source_node")] if observation.get("source_node") else [],
        evidence=[Evidence("cellular_indicator", item, observed_at=now) for item in indicators],
        details={"limitations": "Collector metadata may be incomplete; no single indicator proves interception."},
    )


def route_exposure_score(route_points: list[tuple[float, float]], findings: list[dict], profile: str = "Balanced") -> dict:
    rules = _load_rules()
    profile_mult = {
        "Fastest": 0.4,
        "Balanced": 1.0,
        "Low Exposure": 1.5,
        "Maximum Privacy": 2.2,
    }.get(profile, 1.0)
    total = 0.0
    contributors = []
    for finding in findings:
        details = finding.get("details") or {}
        lat = details.get("latitude") or details.get("center_latitude")
        lon = details.get("longitude") or details.get("center_longitude")
        if lat is None or lon is None or not route_points:
            continue
        distance = min(_distance_m(lat, lon, p[0], p[1]) for p in route_points)
        if distance > 500:
            continue
        confidence_mult = {"LOW": 0.4, "MEDIUM": 0.7, "HIGH": 1.0, "CONFIRMED": 1.2}.get(finding.get("confidence"), 0.5)
        weight = rules["route_weights"].get(finding.get("family"), 1.0)
        score = weight * confidence_mult * profile_mult * max(0.0, 1.0 - distance / 500.0)
        total += score
        contributors.append({"family": finding.get("family"), "label": finding.get("label"), "score": round(score, 2), "distance_m": round(distance, 1)})
    return {"profile": profile, "score": round(total, 2), "contributors": contributors}


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _recommendation_for_family(family: str) -> str:
    if family in {"surveillance.flock", "surveillance.alpr"}:
        return "Preserve evidence and map as surveillance infrastructure; do not interfere with equipment."
    if family.startswith("network."):
        return "Use defensive network checks only: disconnect, inspect gateway/DNS, and verify hardware."
    if family.startswith("tracking."):
        return "Observe over multiple movement sessions and mark ownership before escalating."
    if family.startswith("public_safety."):
        return "Check speed and drive legally; do not use this for pursuit or stop evasion."
    if family.startswith("cellular."):
        return "Record context and compare with baseline; do not treat one event as proof of interception."
    return "Review evidence and update ownership or manual confirmation if needed."
