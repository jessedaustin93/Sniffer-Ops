"""
Central data-dir, identity, and config resolution for SnifferOps Linux.

Single source of truth shared by the headless hub (``snifferops_linux.py``)
and the GTK desktop GUI (``snifferops_gui.py``) so both agree on where the
node identity, config, database, and logs live.

Data directory precedence:
  1. ``$SNIFFEROPS_DATA_DIR``  — the appliance points this at
     ``/var/lib/snifferops`` (writable data partition, read-only root).
  2. ``~/.snifferops``        — desktop default.

The node identity is persisted once and kept stable across restarts, fixing
the old bug where the headless hub regenerated ``NODE_ID`` on every launch.
"""

import json
import os
import uuid
from typing import Any


def data_dir() -> str:
    """Return the resolved data directory (does not create it)."""
    override = os.environ.get("SNIFFEROPS_DATA_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.expanduser("~/.snifferops")


def ensure_data_dir() -> str:
    """Return the data directory, creating it if absent."""
    d = data_dir()
    os.makedirs(d, exist_ok=True)
    return d


# Resolved once at import; callers that need creation use ensure_data_dir()
# or the helpers below (which create as needed).
DATA_DIR = data_dir()
LOG_PATH = os.path.join(DATA_DIR, "awareness.json")
DB_PATH = os.path.join(DATA_DIR, "awareness.db")
CFG_PATH = os.path.join(DATA_DIR, "config.json")
NODE_ID_PATH = os.path.join(DATA_DIR, "node_id")
TRUSTED_DEVICES_PATH = os.path.join(DATA_DIR, "trusted_devices.json")

# Default map home — a generic in-region placeholder (Knoxville, TN). Override
# per install via config.json; no real location ships in source.
DEFAULT_HOME_LAT = 35.9606
DEFAULT_HOME_LON = -83.9207
DEFAULT_HOME_ZOOM = 11

# Default config written on first boot when config.json is absent. Keys match
# what snifferops_gui.py has always read/written so the hub and GUI agree.
DEFAULT_CONFIG: dict[str, Any] = {
    "port": 8766,
    "bind": "0.0.0.0",
    "wifi": True,
    "bluetooth": True,
    "sdr": False,          # enabled per-unit once RTL-SDR hardware is confirmed
    "cellular": False,     # requires dedicated HW; off by default
    "sdr_remote": "",
    "peers": [],
    "home_lat": DEFAULT_HOME_LAT,
    "home_lon": DEFAULT_HOME_LON,
    "home_zoom": DEFAULT_HOME_ZOOM,
}


def load_or_create_node_id() -> str:
    """Read the persisted node id, creating and writing one once if absent.

    The same value is returned across reboots. Any pre-existing id (e.g. one
    the GUI already wrote) is preserved verbatim.
    """
    ensure_data_dir()
    if os.path.exists(NODE_ID_PATH):
        with open(NODE_ID_PATH) as f:
            existing = f.read().strip()
        if existing:
            return existing
    nid = uuid.uuid4().hex[:16]
    tmp = NODE_ID_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(nid)
    os.replace(tmp, NODE_ID_PATH)
    return nid


def load_config() -> dict:
    """Return config.json merged over DEFAULT_CONFIG (defaults fill gaps)."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CFG_PATH) as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update(user)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def bootstrap_config() -> dict:
    """Write a default config.json if missing; return the effective config."""
    ensure_data_dir()
    if not os.path.exists(CFG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    return load_config()


def save_config(cfg: dict) -> None:
    """Atomically write config.json."""
    ensure_data_dir()
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CFG_PATH)
