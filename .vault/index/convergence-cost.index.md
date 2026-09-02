---
generated: true
tags:
  - '#index'
  - '#convergence-cost'
date: '2026-08-14'
modified: '2026-09-02'
body_schema: 'body-v2'
body_hash: 'sha256:09f4d0db7be25beebe0f1639959ced492f65a744b6317cb500e7747157a05c9b'
related:
  - '[[2026-07-28-convergence-cost-P01-S01]]'
  - '[[2026-07-28-convergence-cost-P01-S02]]'
  - '[[2026-07-28-convergence-cost-P01-S03]]'
  - '[[2026-07-28-convergence-cost-P01-S04]]'
  - '[[2026-07-28-convergence-cost-P02-S05]]'
  - '[[2026-07-28-convergence-cost-P02-S06]]'
  - '[[2026-07-28-convergence-cost-P02-S07]]'
  - '[[2026-07-28-convergence-cost-adr]]'
  - '[[2026-07-28-convergence-cost-audit]]'
  - '[[2026-07-28-convergence-cost-plan]]'
  - '[[2026-07-28-convergence-cost-research]]'
---

# `convergence-cost` feature index

Auto-generated index of all documents tagged with `#convergence-cost`.

## Documents

### adr

- `2026-07-28-convergence-cost-adr` - `convergence-cost` adr: `Stat-evidence rehash gate and scoped convergence retention` | (**status:** `accepted`)

### audit

- `2026-07-28-convergence-cost-audit` - 2026-07-28-convergence-cost-audit

### exec

- `2026-07-28-convergence-cost-P01-S01` - Create the shared stat-evidence gate module with advisory sidecar persistence, racy-window trust rule, and fail-toward-rehash semantics
- `2026-07-28-convergence-cost-P01-S02` - Wire the gate into the codebase indexer hashing loop and persist evidence after full, incremental, and scoped runs
- `2026-07-28-convergence-cost-P01-S03` - Wire the gate into the document indexer unscoped selection and the vault indexer document hashing
- `2026-07-28-convergence-cost-P01-S04` - Add gate unit tests covering hit, miss, racy, corrupt sidecar, stat failure, and deletion pruning, plus an integration proof that a warm unchanged pass skips rehashing
- `2026-07-28-convergence-cost-P02-S05` - Preserve unscoped_required in record_interrupted and record_success instead of forcing escalation, keeping failure, recovery, load, and refresh promotion unchanged
- `2026-07-28-convergence-cost-P02-S06` - Update retry-state tests pinning the old escalation and add tests proving scoped retention plus every preserved escalation path
- `2026-07-28-convergence-cost-P02-S07` - Run lint, format, type-check, and the targeted test set, then land the change

### plan

- `2026-07-28-convergence-cost-plan` - `convergence-cost` plan

### research

- `2026-07-28-convergence-cost-research` - `convergence-cost` research: `Why a menial watcher event costs a full-tree rehash`
