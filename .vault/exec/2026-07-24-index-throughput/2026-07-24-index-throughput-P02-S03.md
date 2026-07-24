---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S03'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# pass explicit non-blocking wait semantics on rebuild-path upserts and add the completion barrier before stale-purge and metadata publish

## Scope

- `src/vaultspec_rag/store.py`
- `indexer terminal paths`

## Description

Explicit rebuild-path ingest wait policy with an applied-points barrier (commit `11a6ee57`). Upsert methods gain `wait: bool = True`; the guarded upsert passes `wait=False` only in server mode; the code and vault full-index paths thread `ingest_wait=False` explicitly while incremental paths keep blocking waits unchanged; the ENOSPC/WAL-full versus transient classification is untouched. `VaultStore.apply_ingest_barrier` (server-mode-only, local inert): an idempotent blocking delete of a reserved UUID sentinel fences all prior acknowledged updates in WAL order, then `count(exact=True) == expected_points` catches the acknowledged-but-never-applied silent-drop class that ordering alone cannot (reproduced live against the pinned 1.18.2 with an unknown vector name). Any shortfall raises `IngestVerificationError` and fails the job. Placement: before stale-reconcile and metadata publish in both the code and vault full-index paths, with exact expected-count formulas per path. The barrier fences the collection, not a caller, so the planned writer-side upsert queue adopts it unchanged. Deliberately excluded and reported: the document indexer's rebuild keeps blocking waits (its per-file interleaved delete/upsert ledger makes an exact mid-run expectation ambiguous - wired together with the pipeline-overlap rework). Documented residual: a crash after a silently-dropped acknowledged batch but before the barrier lets a resumed generation trust that batch's ledger unit; any completing run catches it.

## Outcome

## Notes
