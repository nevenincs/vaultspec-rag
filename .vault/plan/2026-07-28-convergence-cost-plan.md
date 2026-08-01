---
tags:
  - '#plan'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_hash: 'sha256:fdd926cfa2dcd2392455cf3909573fa3d6a17ae28b788a6706d3714501efcda6'
tier: L2
related:
  - '[[2026-07-28-convergence-cost-adr]]'
  - '[[2026-07-28-convergence-cost-research]]'
---

# `convergence-cost` plan

### Phase `P01` - Stat-evidence rehash gate

Give every domain's change detection a shared stat-evidence gate so an unscoped convergence pass costs stat calls plus changed bytes instead of rehashing the whole tree.

- [x] `P01.S01` - Create the shared stat-evidence gate module with advisory sidecar persistence, racy-window trust rule, and fail-toward-rehash semantics; `src/vaultspec_rag/indexer/_stat_gate.py`.
- [x] `P01.S02` - Wire the gate into the codebase indexer hashing loop and persist evidence after full, incremental, and scoped runs; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P01.S03` - Wire the gate into the document indexer unscoped selection and the vault indexer document hashing; `src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/indexer/_vault_indexer.py`.
- [x] `P01.S04` - Add gate unit tests covering hit, miss, racy, corrupt sidecar, stat failure, and deletion pruning, plus an integration proof that a warm unchanged pass skips rehashing; `src/vaultspec_rag/tests/test_stat_gate.py, src/vaultspec_rag/tests/integration`.

### Phase `P02` - Scoped convergence retention

Stop the durable retry state from escalating benign interruptions and mid-attempt successes to unscoped convergence while preserving every process-boundary escalation path.

- [x] `P02.S05` - Preserve unscoped_required in record_interrupted and record_success instead of forcing escalation, keeping failure, recovery, load, and refresh promotion unchanged; `src/vaultspec_rag/watcher_retry.py`.
- [x] `P02.S06` - Update retry-state tests pinning the old escalation and add tests proving scoped retention plus every preserved escalation path; `src/vaultspec_rag/tests`.
- [x] `P02.S07` - Run lint, format, type-check, and the targeted test set, then land the change; `src/vaultspec_rag`.

## Description

## Steps

## Parallelization

## Verification
