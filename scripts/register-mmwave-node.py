#!/usr/bin/env python3
"""Register one mmWave field node and print its one-time build secret."""
import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "linux")))
from mmwave_presence import PresenceIngress, PresenceIngressError  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--registry", required=True)
parser.add_argument("--node-id", required=True)
parser.add_argument("--node-name", required=True)
parser.add_argument("--header-output", help="write the generated ESP header mode 0600 instead of stdout")
args = parser.parse_args()
ingress = PresenceIngress()
ingress.configure(args.registry)
try:
    secret = ingress.register_node(args.node_id, args.node_name)
except PresenceIngressError as exc:
    raise SystemExit(f"registration failed: {exc}")
header = (
    "// Generated during secure mmWave node registration. Never commit this file.\n"
    f'#define ETHROX_NODE_ID "{args.node_id}"\n'
    f'#define ETHROX_NODE_NAME "{args.node_name}"\n'
    f'#define ETHROX_NODE_SECRET "{secret}"\n'
)
if args.header_output:
    destination = os.path.abspath(args.header_output)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(header)
    os.chmod(destination, 0o600)
    print(f"Registered {args.node_id}; wrote protected ESP header to {destination}")
else:
    print(f"Registered {args.node_id}. Copy this once into the untracked ESP build secret:")
    print(header, end="")
