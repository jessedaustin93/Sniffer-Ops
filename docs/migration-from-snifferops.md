# Migration From SnifferOps

Ethrox Detect was formerly developed under the SnifferOps codename.

This repository now uses the Ethrox Detect identity for current product names,
service names, packages, paths, launchers, artifacts, and documentation.
Historical commits are intentionally preserved.

## Compatibility Window

Current code and deployed launch paths use Ethrox Detect names. Temporary
compatibility paths should be removed after each migrated node is validated.

## Local Data

The Linux migration script backs up old local state before moving data into the
Ethrox Detect layout. Backups are never deleted automatically.

Private captures, GPS history, databases, node IDs, trusted-device rules,
credentials, and local identifiers must stay out of Git.
