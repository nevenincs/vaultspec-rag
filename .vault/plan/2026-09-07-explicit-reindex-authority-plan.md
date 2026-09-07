---
tags:
  - '#plan'
  - '#explicit-reindex-authority'
date: '2026-09-07'
tier: L3
related:
  - '[[2026-09-07-explicit-reindex-authority-adr]]'
  - '[[2026-09-07-explicit-reindex-authority-research]]'
modified: '2026-09-07'
body_schema: body-v2
body_hash: 'sha256:e57a9da6671e995118bcc4c81c4918ec03a9831dcc9e3e96097e482d72534070'
---

# `explicit-reindex-authority` plan

Prevent every automatic or incremental path from silently entering full-corpus indexing, then make explicitly authorized rebuilds reliable and observable.

## Description

This plan executes the accepted explicit-reindex-authority decision. Wave W01 installs the non-bypassable authority boundary and typed refusal. Wave W02 prevents backend ambiguity, search requests, and lost watcher scope from manufacturing full-work authority. Wave W03 fixes the liveness and observability defects that made the production incident hard to detect and impossible to complete, then proves the invariant through mutation-capable guards and integration tests.

## Steps

## Wave `W01` - Enforce explicit indexing authority

Establish the typed refusal and make every incremental indexer incapable of entering full-corpus execution; later waves depend on this boundary.

### Phase `W01.P01` - Define the refusal contract

Add one typed service-domain outcome and remediation for detected work that requires explicit full-reindex authority.

- [x] `W01.P01.S01` - Add full-reindex-required taxonomy and remediation; `src/vaultspec_rag/_job_errors.py`.
- [x] `W01.P01.S02` - Expose requested and effective indexing cost class in job state; `src/vaultspec_rag/job_models.py`.

### Phase `W01.P02` - Remove silent indexer escalation

Replace code, document, and vault incremental-to-full transitions while retaining explicit full entry points.

- [x] `W01.P02.S03` - Refuse every code incremental-to-full transition with typed detail; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W01.P02.S04` - Refuse document and vault incremental-to-full transitions with typed detail; `src/vaultspec_rag/indexer`.

## Wave `W02` - Preserve bounded automatic recovery

Bind evidence to its backend, preserve watcher scope, and keep search-time integrity detection from initiating unbounded mutation.

### Phase `W02.P03` - Bind publication evidence to storage

Make sidecars and checkpoints distinguish local and managed backend evidence without rebuilding older or foreign evidence.

- [x] `W02.P03.S05` - Persist and compare backend identity in publication evidence; `src/vaultspec_rag/indexer`.
- [x] `W02.P03.S06` - Carry backend identity through store and checkpoint construction; `src/vaultspec_rag/store_runtime.py`.

### Phase `W02.P04` - Bound automatic initiators and recovery scope

Keep search read-only by default and recover exact watcher scope or stop with the typed refusal.

- [x] `W02.P04.S07` - Disable search-triggered mutation by default while retaining integrity reporting; `src/vaultspec_rag/_integrity_remediation.py, src/vaultspec_rag/config/_settings.py`.
- [x] `W02.P04.S08` - Refuse watcher recovery when its bounded path scope is unavailable; `src/vaultspec_rag/watcher_retry.py`.
- [x] `W02.P04.S09` - Stop automatic retries for full-reindex-required outcomes; `src/vaultspec_rag/watcher_retry.py`.

## Wave `W03` - Make authorized rebuilds reliable and observable

Instrument reconciliation progress, health, compatibility logging, startup guidance, and end-to-end guards after the authority boundary is stable.

### Phase `W03.P05` - Instrument finalization and service health

Recognize durable cleanup work, propagate degradation, and preserve compatibility causes.

- [x] `W03.P05.S10` - Record durable progress for committed reconciliation batches; `src/vaultspec_rag/indexer/_route_migration.py, src/vaultspec_rag/indexer/_run_policy.py`.
- [x] `W03.P05.S11` - Propagate degraded job counts and effective operation through health; `src/vaultspec_rag/server`.
- [x] `W03.P05.S12` - Log compatibility causes and correct local-only startup guidance; `src/vaultspec_rag/server/_lifespan.py, src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_document_indexer.py`.

### Phase `W03.P06` - Prove the system invariant

Exercise cross-backend, watcher, search, timeout, health, and explicit rebuild behavior through guard and integration tests.

- [x] `W03.P06.S13` - Add mutation-proven unit guards for automatic full-work refusal; `src/vaultspec_rag/tests`.
- [x] `W03.P06.S14` - Add integration coverage for backend transitions and contended finalization; `src/vaultspec_rag/tests/integration/test_reindex_consent_boundary.py, src/vaultspec_rag/tests/test_watcher_retry.py`.

## Parallelization

Waves execute in order. Within W01, S01 precedes S03 and S04; S02 can proceed independently once the taxonomy is stable. Within W02, S05 precedes S06 and the backend-transition portions of S07; S08 precedes S09. Within W03, S10, S11, and S12 are independent after W02. Test steps follow their corresponding production changes and converge in S14.

## Verification

- A guard replacing each incremental full-call target proves it can fail and every automatic-path test still passes without calling that target.
- Code, document, and vault incrementals return `full_reindex_required` for missing, short, incompatible, layout-drift, and content-drift evidence while explicit rebuild entry points still complete.
- A server-to-local and local-to-server transition classifies foreign evidence as unverifiable and admits no integrity repair.
- Restarted watcher state either restores the bounded canonical path set or terminates with `full_reindex_required`; it never resolves unknown scope to `None`.
- Route reconciliation can exceed the nominal no-progress interval while committing cleanup batches, but expires when no durable cleanup or publication boundary occurs.
- `/health` becomes degraded for a degraded indexing job before the stalled threshold and carries requested/effective cost class.
- Managed startup guidance states that local-only is a distinct index and never presents it as recovery of managed data.
- Focused unit and integration suites, static gates, full vault checks, formal review, and PR checks pass.
