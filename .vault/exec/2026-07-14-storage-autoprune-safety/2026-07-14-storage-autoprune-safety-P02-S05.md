---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:a015d1d97c05b4cecd81a6a8ed573b270c9856f1f12165345162c242eff14a5f'
step_id: 'S05'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Add the maintenance cycle function (survey, grace bookkeeping, capped two-tier reclamation, archive retention, one-line health rollup with disk-free warning) and the crash-proof \_maintenance_loop task mirroring \_heartbeat_loop

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Add `_storage_maintenance_tick_sync`: server-mode/knob gated, builds the
  `ReclaimPolicy` from config, opens a short-lived client to the managed
  server, runs `run_maintenance_cycle`, and emits one structured
  `service.maintenance cycle` rollup line (removed/failed/pending/dangling
  bytes/archive counts/namespace statuses) plus a `disk_low` warning under
  a 10GB free-space threshold.
- Add `_maintenance_loop`: same crash-proof shape as `_heartbeat_loop`,
  first run delayed one full interval, interval re-read from config each
  tick (floored at 1s so tests can run short cadences), no exception may
  escape.
- Export both through the server package alias so lifespan wiring and
  tests reach them like the heartbeat helpers.

## Outcome

The cycle is pure storage IO behind the stacked gates; 119 server unit
tests pass; ruff, ruff format, and basedpyright clean.

## Notes

Jobs-registry registration and the /metrics gauges land in S07 per the
plan split; this step's observability is the log rollup.
