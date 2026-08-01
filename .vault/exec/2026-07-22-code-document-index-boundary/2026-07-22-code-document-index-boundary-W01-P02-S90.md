---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:e5854d8ef4029cf8ffaf887ae84bfcd422a1ee543a90b95996e16bbb8fa1c127'
step_id: 'S90'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Thread the exact resolved snapshot through worker execution, epochs, ledger signatures, and metadata publication without a second configuration load

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `src/vaultspec_rag/indexer/_preprocess_glue.py`
- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Materialize worker preprocessing and decoder state from the immutable policy.
- Derive code epochs and publication metadata from the same per-kind fingerprints.
- Pass the frozen execution policy through serial, batch, and process-pool chunk paths.

## Outcome

Admission, worker execution, epoch comparison, and metadata publication observe one policy
snapshot without reopening mutable configuration.

## Notes

Reconciled from production commit `95e9b05`; no additional code change was required.
