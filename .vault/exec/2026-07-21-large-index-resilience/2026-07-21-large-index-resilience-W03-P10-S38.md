---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S38'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify service-job-control cooperative indexing phases use ledger safe points and preserve one-unit replay

## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

- Exercise pause and cancellation through the production code-index pipeline.
- Resume compatible generations and verify replay starts after the last storage-confirmed commit unit.
- Exercise clean-rebuild publication and verify pending control is deferred until collection and metadata publication are current.
- Assert exact point identities and converged metadata after cooperative unwind and restart.

## Outcome

Service job control now has production-path verification across ordinary commit-unit boundaries and protected publication spans. Pause and cancellation preserve confirmed ledger progress, compatible restart replays only unconfirmed work, and clean publication cannot expose a half-published generation.

## Notes

The phase-boundary selection passed 3 cases: pause, cancellation, and clean-publication deferral. The tests use the real indexer, SQLite ledger, metadata sidecar, local vector store, and production control token; no fakes, mocks, stubs, patches, monkeypatches, skips, or expected failures were used.
