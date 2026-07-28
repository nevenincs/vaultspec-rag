---
tags:
  - '#exec'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
step_id: 'S03'
related:
  - "[[2026-07-28-convergence-cost-plan]]"
---

# Wire the gate into the document indexer unscoped selection and the vault indexer document hashing

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`
- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Route the document indexer's unscoped `_select_incremental_paths` branch through the gate with prune and persist; delete the orphaned `_hash_path` helper.
- Route `VaultIndexer._hash_documents` through the gate with `full_membership` on the unscoped caller.

## Outcome

All three domains consult one gate implementation; no duplicate hashing logic remains.

## Notes

The vault domain's post-run meta save still rehashes each just-indexed document; that cost is proportional to the change set and was deliberately left ungated.
