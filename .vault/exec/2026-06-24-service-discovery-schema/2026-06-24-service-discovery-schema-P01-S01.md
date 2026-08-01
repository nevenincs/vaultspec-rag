---
tags:
  - '#exec'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
body_hash: 'sha256:cf04b96a57b83a5871dfe9d572ab8273a27ea9e770a6b50a9941bc96f6ed0beb'
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
