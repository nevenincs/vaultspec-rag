---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:242ef87bc8ac1618ccd4ebcf136cc29f686f930b2d29f4aa29d5c512e91e7d9f'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# `storage-autoprune-safety` `P02` summary

All five Steps complete (S05 tick and loop, S06 lifespan wiring, S07
jobs and metrics, S08 lifecycle-inertness guards, S09 live integration
test), one commit per Step.

- Modified: `src/vaultspec_rag/server/_lifecycle.py`
- Modified: `src/vaultspec_rag/server/_lifespan.py`
- Modified: `src/vaultspec_rag/server/_state.py`
- Modified: `src/vaultspec_rag/server/__init__.py`
- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/tests/test_adr_regression.py`
- Created: `src/vaultspec_rag/tests/integration/test_storage_maintenance.py`

## Description

The daemon now owns reclamation: a lifespan task mirroring the
heartbeat's crash-proof shape runs `_storage_maintenance_tick_sync` on
the configured cadence (first run delayed one interval; server-mode and
knob gated), each cycle a first-class `source=maintenance trigger=schedule` job with a one-line rollup and a 10GB disk-low
warning, and the inline `/metrics` holder gained the maintenance
counters and gauges. Two regression guards pin lifecycle inertness (a
fresh-interpreter import-graph check and a source scan for the terminate
helpers). The live integration test staged three real namespaces and
proved the contract end to end - and earned its keep by catching two
real bugs on its first run: the int-typed interval knob rejecting
fractional minutes, and a failure path with no await point that pinned
the event loop and starved every request handler (fixed with a
60-second backoff). Verification: 1/1 live in 42s twice (before and
after the review's pre-drop re-count), 134 server+jobs unit tests
green, audit passed.
