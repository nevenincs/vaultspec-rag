---
generated: true
tags:
  - '#index'
  - '#storage-autoprune-safety'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - '[[2026-07-13-storage-autoprune-safety-research]]'
  - '[[2026-07-14-storage-autoprune-safety-P01-S01]]'
  - '[[2026-07-14-storage-autoprune-safety-P01-S02]]'
  - '[[2026-07-14-storage-autoprune-safety-P01-S03]]'
  - '[[2026-07-14-storage-autoprune-safety-P01-S04]]'
  - '[[2026-07-14-storage-autoprune-safety-P01-summary]]'
  - '[[2026-07-14-storage-autoprune-safety-P02-S05]]'
  - '[[2026-07-14-storage-autoprune-safety-P02-S06]]'
  - '[[2026-07-14-storage-autoprune-safety-P02-S07]]'
  - '[[2026-07-14-storage-autoprune-safety-P02-S08]]'
  - '[[2026-07-14-storage-autoprune-safety-P02-S09]]'
  - '[[2026-07-14-storage-autoprune-safety-P02-summary]]'
  - '[[2026-07-14-storage-autoprune-safety-P03-S10]]'
  - '[[2026-07-14-storage-autoprune-safety-P03-S11]]'
  - '[[2026-07-14-storage-autoprune-safety-P03-summary]]'
  - '[[2026-07-14-storage-autoprune-safety-adr]]'
  - '[[2026-07-14-storage-autoprune-safety-audit]]'
  - '[[2026-07-14-storage-autoprune-safety-plan]]'
---

# `storage-autoprune-safety` feature index

Auto-generated index of all documents tagged with `#storage-autoprune-safety`.

## Documents

### adr

- `2026-07-14-storage-autoprune-safety-adr` - `storage-autoprune-safety` adr: `scheduled in-daemon auto-prune with a grace-window safety contract` | (**status:** `accepted`)

### audit

- `2026-07-14-storage-autoprune-safety-audit` - `storage-autoprune-safety` audit: `execution review of the scheduled auto-prune and attribution`

### exec

- `2026-07-14-storage-autoprune-safety-P01-S01` - Add the first_seen_orphaned field to ManifestEntry with lenient load of pre-upgrade manifests, plus stamp/clear helpers that persist the grace clock across daemon restarts and reset it when a root reappears
- `2026-07-14-storage-autoprune-safety-P01-S02` - Add grace-window evaluation and two-tier reclamation eligibility (empty orphans past grace_hours and point-bearing orphans past grace_hours_data) plus the per-collection snapshot-archive helper and the byte-capped, age-capped archive retention sweep
- `2026-07-14-storage-autoprune-safety-P01-S03` - Add the storage_autoprune knobs (enabled, interval_minutes, grace_hours, grace_hours_data, archive_retention_days, max_per_cycle) following the existing env and config-file naming
- `2026-07-14-storage-autoprune-safety-P01-S04` - Cover the grace bookkeeping and eligibility gates with unit tests: stamping, restart persistence, reappearance reset, empty-vs-data tiering, cap enforcement, and archive retention
- `2026-07-14-storage-autoprune-safety-P01-summary` - `storage-autoprune-safety` `P01` summary
- `2026-07-14-storage-autoprune-safety-P02-S05` - Add the maintenance cycle function (survey, grace bookkeeping, capped two-tier reclamation, archive retention, one-line health rollup with disk-free warning) and the crash-proof \_maintenance_loop task mirroring \_heartbeat_loop
- `2026-07-14-storage-autoprune-safety-P02-S06` - Start and cancel the maintenance task in the daemon lifespan, delayed one interval after startup and gated on server mode plus the storage_autoprune knob
- `2026-07-14-storage-autoprune-safety-P02-S07` - Register each cycle in the jobs registry with source maintenance and trigger schedule, and export the rollup gauges (disk free, namespace counts by status, dangling bytes, pending-grace counts) through /metrics and server status
- `2026-07-14-storage-autoprune-safety-P02-S08` - Prove lifecycle inertness with an import-graph regression test asserting no module reachable from the maintenance cycle imports the stop, terminate, or machine-singleton reclaim helpers
- `2026-07-14-storage-autoprune-safety-P02-S09` - Exercise the maintenance cycle end to end against a live service with a short interval: an aged empty orphan is reclaimed, a fresh orphan waits, a reappearing root resets its clock, and the cycle appears in server jobs
- `2026-07-14-storage-autoprune-safety-P02-summary` - `storage-autoprune-safety` `P02` summary
- `2026-07-14-storage-autoprune-safety-P03-S10` - Carry initiator identity (pid, argv command line, cwd) on the cli_terminate audit event and in the stop and stop-port envelope data
- `2026-07-14-storage-autoprune-safety-P03-S11` - Assert the attribution fields appear in the shutdown log line and the stop --json envelopes across the stop exit paths
- `2026-07-14-storage-autoprune-safety-P03-summary` - `storage-autoprune-safety` `P03` summary

### plan

- `2026-07-14-storage-autoprune-safety-plan` - `storage-autoprune-safety` plan

### research

- `2026-07-13-storage-autoprune-safety-research` - `storage-autoprune-safety` research: `service-kill trace and scheduled auto-prune design`
