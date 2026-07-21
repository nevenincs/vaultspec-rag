---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S14'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add the ephemeral idle-TTL reclaim tier to evaluate_reclaim and run_maintenance_cycle behind a config knob, reusing the empty/data tiers and destruction gates, and carry the ephemeral flag on survey rows

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

`ReclaimPolicy` gains `ephemeral_idle_hours` (default 72, 0 disables;
knob `storage_autoprune_ephemeral_idle_hours`). `_evaluate_ephemeral`
considers only `live` + `is_temp_rooted` namespaces: missing/unparsable
stamp is pending, fresh activity is pending with remaining hours, expired
TTL yields `reclaim_empty`/`reclaim_data` with reason `ephemeral_idle`,
reusing the unchanged destruction actions so the maintenance apply path
(archive-before-drop for data, TOCTOU re-count for empty, `delete_prefix`
gates) needs no change. Orphans keep priority under the shared per-cycle
cap. `run_maintenance_cycle` feeds the tier from `load_manifest()`.

## Outcome

Committed as `feat(storage): ephemeral idle-TTL reclaim tier for live temp-rooted namespaces (#242)`; lifecycle-inertness regression suite
stays green.

## Notes

`unknown`/`unverifiable` namespaces never reach the tier (they are not
`live`), honoring the time-confirmed-danglingness rule; the ADR records
the danglingness-definition extension explicitly.
