---
tags:
  - '#exec'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S01'
related:
  - "[[2026-06-24-service-discovery-schema-plan]]"
---




# Normalise the CLI-parent initial write of started_at to ISO-8601 with offset at second precision, matching the heartbeat last_heartbeat format

## Scope

- `src/vaultspec_rag/cli/_service_status.py`

## Description

- Replaced the CLI-parent `started_at` write with the shared `_discovery_timestamp()` helper (ISO-8601 with offset, second precision).

## Outcome

The CLI-parent `started_at` now matches the heartbeat `last_heartbeat` format exactly; the microsecond-vs-second divergence is gone.

## Notes

No incidents; no scaffolds left in code.
