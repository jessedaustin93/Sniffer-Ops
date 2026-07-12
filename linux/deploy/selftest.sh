#!/usr/bin/env bash
# SnifferOps appliance self-test / assembly test.
#
# Run on the unit (or over SSH) to confirm a node is healthy before it ships.
# Exits non-zero if any REQUIRED check fails; optional hardware checks warn only.
#
# Usage:  ./selftest.sh [--port N] [--data-dir DIR]
set -uo pipefail

PORT=8766
DATA_DIR="${SNIFFEROPS_DATA_DIR:-/var/lib/snifferops}"
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

PASS=0; FAIL=0; WARN=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; WARN=$((WARN+1)); }

echo "SnifferOps self-test  (port=$PORT data=$DATA_DIR)"

# ── Service ──────────────────────────────────────────────────────────────────
if systemctl is-active --quiet snifferops.service; then
    ok "snifferops.service is active"
else
    bad "snifferops.service is not active"
fi

# ── API ──────────────────────────────────────────────────────────────────────
API_JSON="$(curl -s -m 5 "localhost:$PORT/snifferops/awareness" || true)"
if echo "$API_JSON" | grep -q '"nodeId"'; then
    API_NODE="$(echo "$API_JSON" | sed -n 's/.*"nodeId": *"\([^"]*\)".*/\1/p')"
    ok "API answers on $PORT (nodeId=$API_NODE)"
else
    bad "API did not answer on localhost:$PORT"
    API_NODE=""
fi

# ── Persisted identity ───────────────────────────────────────────────────────
if [ -s "$DATA_DIR/node_id" ]; then
    FILE_NODE="$(cat "$DATA_DIR/node_id")"
    ok "node_id persisted ($FILE_NODE)"
    if [ -n "$API_NODE" ] && [ "$API_NODE" != "$FILE_NODE" ]; then
        bad "API nodeId != persisted node_id ($API_NODE vs $FILE_NODE)"
    fi
else
    bad "node_id not persisted at $DATA_DIR/node_id"
fi

# ── Config valid JSON ────────────────────────────────────────────────────────
if [ -f "$DATA_DIR/config.json" ] && python3 -c "import json,sys; json.load(open('$DATA_DIR/config.json'))" 2>/dev/null; then
    ok "config.json present and valid JSON"
else
    bad "config.json missing or invalid at $DATA_DIR/config.json"
fi

# ── Data dir writable by the service user ────────────────────────────────────
if sudo -u snifferops test -w "$DATA_DIR" 2>/dev/null || [ -w "$DATA_DIR" ]; then
    ok "data dir writable"
else
    bad "data dir not writable: $DATA_DIR"
fi

# ── Bluetooth adapter (optional HW) ──────────────────────────────────────────
if command -v bluetoothctl >/dev/null 2>&1 && bluetoothctl list 2>/dev/null | grep -q Controller; then
    ok "Bluetooth adapter present"
else
    warn "no Bluetooth adapter enumerated"
fi

# ── RTL-SDR (optional HW) ────────────────────────────────────────────────────
if command -v rtl_test >/dev/null 2>&1 && rtl_test -t 2>&1 | grep -qi 'Found'; then
    ok "RTL-SDR device enumerated"
else
    warn "no RTL-SDR device enumerated (fine if none fitted)"
fi

echo "----------------------------------------"
echo "PASS=$PASS  FAIL=$FAIL  WARN=$WARN"
[ "$FAIL" -eq 0 ] && { echo "RESULT: OK"; exit 0; } || { echo "RESULT: FAILED"; exit 1; }
