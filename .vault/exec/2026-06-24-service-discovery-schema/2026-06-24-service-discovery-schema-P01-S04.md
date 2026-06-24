---
tags:
  - '#exec'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S04'
related:
  - "[[2026-06-24-service-discovery-schema-plan]]"
---

# Emit heartbeat_interval_s and stale_after_s from the same config the heartbeat loop uses so the liveness contract is machine-readable

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Emitted `heartbeat_interval_s` and `stale_after_s` from `_HEARTBEAT_INTERVAL_SECONDS`/`_HEARTBEAT_STALENESS_SECONDS` in the heartbeat merge.

## Outcome

The staleness contract is now machine-readable in the file, sourced from the same constants the heartbeat loop uses.

## Notes

No incidents; no scaffolds left in code.
