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
args = parser.parse_args()
ingress = PresenceIngress()
ingress.configure(args.registry)
try:
    secret = ingress.register_node(args.node_id, args.node_name)
except PresenceIngressError as exc:
    raise SystemExit(f"registration failed: {exc}")
print(f"Registered {args.node_id}. Copy this once into the untracked ESP build secret:")
print(f'#define ETHROX_MMWAVE_NODE_ID "{args.node_id}"')
print(f'#define ETHROX_MMWAVE_NODE_SECRET "{secret}"')
