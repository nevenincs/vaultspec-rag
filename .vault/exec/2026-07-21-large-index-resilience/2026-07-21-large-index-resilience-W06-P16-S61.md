---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:01acb751853177389533a8e4762db3ca6222d0895fe28718f0dbf2dc84d4522a'
step_id: 'S61'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Apply the same connection contract to the route-migration journal

## Scope

- `src/vaultspec_rag/indexer/_route_migration.py`

## Description

- Route the route-migration journal in `src/vaultspec_rag/indexer/_route_migration.py` through the same shared opener rather than a second connect helper.
- Give its two write paths real transactions; they had relied on the driver's context manager to commit.
- Delete the module's own connect helper.

## Outcome

Both durable databases now open under one contract with one implementation. A copied opener that drifted on one of them was the realistic regression here, and there is no longer a second one to drift.

The transaction change is a correctness fix beyond the concurrency work: the two write paths previously depended on the driver's implicit commit, which the handle-scoped accessor would have silently stopped providing.

## Notes

The two journal write paths had been relying on the driver's implicit commit. Moving to a handle-scoped accessor without giving them explicit transactions would have silently stopped persisting migration state, so the transactions were added in the same change rather than after it.
