---
tags:
  - '#exec'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
body_hash: 'sha256:0d47f38b2d0c132847a66bf08d6e9d09f335dabcd2461c050ea2e681e2d1da99'
step_id: 'S07'
related:
  - "[[2026-06-24-service-discovery-schema-plan]]"
---

# Add a no-mock test asserting the version is present after the CLI-parent write and preserved across a heartbeat tick, with the atomic-write discipline intact

## Scope

- `src/vaultspec_rag/tests/test_service_discovery_schema.py`

## Description

- Added no-mock assertions that the `version` is present after the CLI-parent write and preserved across a heartbeat tick, and that the atomic write leaves no `.tmp` sibling.

## Outcome

Version survival and the atomic-write discipline are proven; the pre-existing exact-key-set test in `test_cli.py` was updated for the added discriminator fields.

## Notes

No incidents; no scaffolds left in code.
