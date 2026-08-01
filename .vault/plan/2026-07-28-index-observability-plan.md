---
tags:
  - '#plan'
  - '#index-observability'
date: '2026-07-28'
modified: '2026-07-30'
body_hash: 'sha256:52d4ec641bfa69f25443362c2a1836898e12565429af1559840d162175215da7'
tier: L2
related:
  - '[[2026-07-28-index-observability-adr]]'
  - '[[2026-07-28-index-observability-research]]'
---

# `index-observability` plan

### Phase `P01` - Truthful signals

Publish forward-pass runtime from the encode path and turn the single stalled flag into a service-owned three-way degradation verdict, and stop the reindex_failed event from firing on non-terminal transitions.

- [x] `P01.S01` - Publish forward-entry and forward-exit runtime telemetry from the encode slice through the progress reporter into the job runtime block; `src/vaultspec_rag/indexer/_streaming.py, src/vaultspec_rag/jobs.py, src/vaultspec_rag/job_manager`.
- [x] `P01.S02` - Add the service-owned three-way degradation verdict beside stalled in the enriched jobs projection with a short degraded threshold and the existing 300s hard threshold; `src/vaultspec_rag/server/_routes_jobs.py, src/vaultspec_rag/_job_errors.py, src/vaultspec_rag/jobs.py`.
- [x] `P01.S03` - Restrict the reindex_failed event to terminal failures carrying a populated error and give the non-terminal observation its own event name; `src/vaultspec_rag/watcher_runtime.py`.

### Phase `P02` - Cause attribution

Attach sampled evidence - GPU pressure, backend liveness, encode-thread activity - to any unhealthy verdict and render it on the CLI and TUI surfaces verbatim.

- [x] `P02.S04` - Attach the evidence block to unhealthy verdicts: forward age, read-only GPU utilization and memory probe, bounded backend liveness probe with latency, encode-thread liveness; `src/vaultspec_rag/server/_routes_jobs.py, src/vaultspec_rag/jobs.py`.
- [x] `P02.S05` - Render the degradation verdict and evidence on the jobs CLI and TUI from the service payload without entry-point heuristics; `src/vaultspec_rag/cli/_service_jobs_presentation.py, src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P02.S06` - Add unit and integration tests proving each verdict tier, the evidence block shape, the terminal-only reindex_failed event, and prove each guard can fail; `src/vaultspec_rag/tests`.
- [x] `P02.S07` - Run lint, format, type-check, and the targeted test set, then land the change; `src/vaultspec_rag`.

## Description

## Steps

## Parallelization

## Verification
