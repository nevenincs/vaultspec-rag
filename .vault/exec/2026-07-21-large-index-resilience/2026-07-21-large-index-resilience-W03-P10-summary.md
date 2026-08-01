---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8b5923166ba8e9b79de6a7cd2db4ccd487d4ffe54ee4dfb178f8da9ddf1b090b'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` `W03.P10` summary

Checkpoint-aware job control now coordinates ledger commit units, protected publication spans, and typed safety signals through one run-policy authority. Production-path verification proves pause and cancellation preserve confirmed work and that clean publication completes atomically before control is acknowledged.

- Modified: `src/vaultspec_rag/indexer/_run_policy.py`
- Modified: `src/vaultspec_rag/indexer/_run_checkpoint.py`
- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`
- Modified: `src/vaultspec_rag/tests/test_run_policy.py`
- Modified: `src/vaultspec_rag/tests/integration/test_index_job_control.py`
- Created: `2026-07-21-large-index-resilience-W03-P10-S37.md`
- Created: `2026-07-21-large-index-resilience-W03-P10-S38.md`

## Description

The run policy exposes labeled protected spans that validate liveness and pending control at entry and exit while deferring acknowledgment across indivisible mutations. Code indexing routes incremental replacement and clean publication through those spans. The phase boundary passed 3 real pipeline cases for pause, cancellation, compatible one-unit replay, and clean-publication deferral; the lower-level run-policy boundary passed 17 cases.
