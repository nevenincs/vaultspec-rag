---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S17'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Run focused unit and integration suites for configuration, writers, routes, transport, and CLI

## Scope

- `src/vaultspec_rag/tests`

## Description

- Run focused configuration, reader, writer, route, transport, and CLI tests.
- Run real service rollover checks against isolated daemon processes.
- Rerun the consolidated matrix after the supervisor lifecycle revision.

## Outcome

The final focused matrix passes 125 tests; both real service rollover scenarios also pass.

## Notes

One cold model-cache run exceeded its 90-second service startup allowance; the cache-warm rerun completed successfully and the logging assertion passed.
