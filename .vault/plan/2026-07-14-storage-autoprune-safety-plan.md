---
tags:
  - '#plan'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
tier: L2
related:
  - '[[2026-07-14-storage-autoprune-safety-adr]]'
  - '[[2026-07-13-storage-autoprune-safety-research]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `storage-autoprune-safety` plan

### Phase `P01` - Grace bookkeeping and reclamation policy

Give the storage domain the time-confirmed danglingness contract: manifest first-seen-orphaned stamps, two-tier reclamation eligibility, snapshot archiving with bounded retention, and the config knobs.

- [x] `P01.S01` - Add the first_seen_orphaned field to ManifestEntry with lenient load of pre-upgrade manifests, plus stamp/clear helpers that persist the grace clock across daemon restarts and reset it when a root reappears; `src/vaultspec_rag/storage_manifest.py`.
- [ ] `P01.S02` - Add grace-window evaluation and two-tier reclamation eligibility (empty orphans past grace_hours and point-bearing orphans past grace_hours_data) plus the per-collection snapshot-archive helper and the byte-capped, age-capped archive retention sweep; `src/vaultspec_rag/storage_ops.py`.
- [ ] `P01.S03` - Add the storage_autoprune knobs (enabled, interval_minutes, grace_hours, grace_hours_data, archive_retention_days, max_per_cycle) following the existing env and config-file naming; `src/vaultspec_rag/config.py`.
- [ ] `P01.S04` - Cover the grace bookkeeping and eligibility gates with unit tests: stamping, restart persistence, reappearance reset, empty-vs-data tiering, cap enforcement, and archive retention; `src/vaultspec_rag/tests/test_storage_ops.py`.

### Phase `P02` - In-daemon maintenance loop

Schedule the hourly maintenance cycle inside the daemon lifespan, report every cycle through the jobs registry, surface the health rollup, and prove lifecycle inertness.

- [ ] `P02.S05` - Add the maintenance cycle function (survey, grace bookkeeping, capped two-tier reclamation, archive retention, one-line health rollup with disk-free warning) and the crash-proof _maintenance_loop task mirroring _heartbeat_loop; `src/vaultspec_rag/server/_lifecycle.py`.
- [ ] `P02.S06` - Start and cancel the maintenance task in the daemon lifespan, delayed one interval after startup and gated on server mode plus the storage_autoprune knob; `src/vaultspec_rag/server/_lifespan.py`.
- [ ] `P02.S07` - Register each cycle in the jobs registry with source maintenance and trigger schedule, and export the rollup gauges (disk free, namespace counts by status, dangling bytes, pending-grace counts) through /metrics and server status; `src/vaultspec_rag/jobs.py`.
- [ ] `P02.S08` - Prove lifecycle inertness with an import-graph regression test asserting no module reachable from the maintenance cycle imports the stop, terminate, or machine-singleton reclaim helpers; `src/vaultspec_rag/tests/test_adr_regression.py`.
- [ ] `P02.S09` - Exercise the maintenance cycle end to end against a live service with a short interval: an aged empty orphan is reclaimed, a fresh orphan waits, a reappearing root resets its clock, and the cycle appears in server jobs; `src/vaultspec_rag/tests/integration/test_storage_maintenance.py`.

### Phase `P03` - Shutdown attribution

Make every service termination answerable from one log line by carrying initiator identity on the audit event and stop envelopes.

- [x] `P03.S10` - Carry initiator identity (pid, argv command line, cwd) on the cli_terminate audit event and in the stop and stop-port envelope data; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P03.S11` - Assert the attribution fields appear in the shutdown log line and the stop --json envelopes across the stop exit paths; `src/vaultspec_rag/tests/test_cli_server_stop.py`.

## Description

Implements the accepted storage-autoprune-safety ADR: an hourly in-daemon
maintenance loop that reclaims time-confirmed dangling namespaces under a
stacked safety-gate contract (manifest attribution, orphaned classification,
persisted grace windows, empty-vs-data tiering with snapshot archives,
per-cycle caps), reports every cycle through the jobs registry, folds a
disk/health rollup into the same tick, and adds initiator attribution to
service shutdown events. Grounded in the linked research (the 2026-07-13
prune trace and waste-profile findings).

## Steps

## Parallelization

`P01` must land before `P02` (the loop consumes the grace and eligibility
helpers). `P03` is independent and may run in parallel with either. Within
each Phase the Steps are ordered; tests land last in their Phase.

## Verification

- Unit: grace stamping persists across manifest reloads, resets on root
  reappearance, and the eligibility gates enforce tiering and caps
  (`test_storage_ops.py`).
- Integration: a live daemon with a short interval reclaims an aged empty
  orphan, leaves a fresh orphan, resets a reappeared root, and the cycle is
  visible in `server jobs` and the log rollup
  (`test_storage_maintenance.py`).
- The import-graph regression test proves no maintenance-reachable module
  imports the stop/terminate/reclaim helpers.
- Stop envelopes and the `cli_terminate` audit line carry initiator pid,
  command, and cwd on every exit path.
- Full local gate green: ruff, basedpyright, unit + integration suites (the
  resident machine service stopped for the integration run, restarted
  after, per the index-drift closeout note).
