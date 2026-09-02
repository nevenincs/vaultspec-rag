---
tags:
  - '#research'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:6bc4625cf652bf36a70f6e94a29722bdd0f10a3b679c6ca0cf0685a9014e8fa3'
related:
  - "[[2026-09-01-generation-accounting-repair-reference]]"
---

# `generation-accounting` research: `generation accounting repair options`

The recovered generation-accounting branch has three defects that can make a published
index incorrect or an advertised setting ineffective. The evidence favors explicit
active-target ownership and storage-confirmed retirement, while the ADR must settle the
single canonical repair boundary.

## Findings

### Clean-generation cleanup has two possible collection targets

The build pipeline writes to the lifecycle-derived generation collection, whereas omitted
store collection arguments resolve to the still-served collection. Passing the build
target through cleanup retains the served index until publication; rebinding the store
early would expose incomplete content. `src/vaultspec_rag/indexer/_consumer_pipeline.py:674-702`
and `src/vaultspec_rag/store_ingest.py:531-549` establish the two targets.

### A retained upsert needs a real retirement, not a relaxed ledger check

The finalization guard deliberately requires each retained upsert to retain an indexed
state. Deleting only the file-state row or relaxing the check leaves unclaimed storage
points. Deleting the points from the run target and recording a confirmed deletion follows
the existing durability ordering. `src/vaultspec_rag/indexer/_run_ledger_finalization.py:114-140`
and `src/vaultspec_rag/indexer/_incremental_commit.py:222-264` establish that constraint.

### Reindex timeout needs dynamic resolution

The environment setting is declared and validated, but reindex calls pass an import-time
constant. A dedicated resolver parallel to the admin resolver preserves default fallback
while making a current environment or configuration override observable. `src/vaultspec_rag/config/_schema.py:145-148`,
`src/vaultspec_rag/serviceclient/_transport.py:402-439`, and
`src/vaultspec_rag/serviceclient/_transport.py:857-881` establish the mismatch.

### Existing decisions constrain the repair

The accepted non-destructive publication and index-resume decisions require one lifecycle
owner, storage mutation before ledger advancement, and a served pointer that moves only at
publication. The document drift record does not authorize copying code drift mechanics into
the document path. `2026-07-25-non-destructive-index-publication-adr` and
`2026-07-25-index-resume-drift-race-adr` are the governing records.

## Sources

- `src/vaultspec_rag/indexer/_consumer_pipeline.py:411-492`
- `src/vaultspec_rag/indexer/_consumer_pipeline.py:674-702`
- `src/vaultspec_rag/indexer/_incremental_commit.py:222-264`
- `src/vaultspec_rag/indexer/_run_ledger_finalization.py:114-140`
- `src/vaultspec_rag/indexer/_generation_lifecycle.py:170-198`
- `src/vaultspec_rag/serviceclient/_transport.py:402-439`
- `src/vaultspec_rag/serviceclient/_transport.py:857-881`
- `2026-07-25-non-destructive-index-publication-adr`
- `2026-07-25-index-resume-drift-race-adr`
