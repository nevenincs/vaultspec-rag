---
tags:
  - '#exec'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S06'
related:
  - "[[2026-06-24-service-discovery-schema-plan]]"
---




# Add a no-mock test asserting both writers emit the same schema and version and the same timestamp format and precision for started_at and last_heartbeat

## Scope

- `src/vaultspec_rag/tests/test_service_discovery_schema.py`

## Description

- Added a no-mock test driving the real CLI-parent writer and the real heartbeat tick: both emit the same `(schema, version)` and the same ISO second-precision offset format for `started_at` and `last_heartbeat`.

## Outcome

Three tests pass; the cross-writer format/version agreement is guarded.

## Notes

No incidents; no scaffolds left in code.
