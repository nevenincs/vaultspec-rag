---
tags:
  - '#exec'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S03'
related:
  - "[[2026-06-24-service-discovery-schema-plan]]"
---




# Preserve and re-assert the schema, version, and staleness fields in the daemon heartbeat additive merge

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Re-asserted `schema`/`version` and switched `last_heartbeat` to the shared `_discovery_timestamp()` helper in the daemon heartbeat merge.

## Outcome

A file written by an older parent is upgraded on the first tick; both writers now share one timestamp format and one discriminator.

## Notes

No incidents; no scaffolds left in code.
