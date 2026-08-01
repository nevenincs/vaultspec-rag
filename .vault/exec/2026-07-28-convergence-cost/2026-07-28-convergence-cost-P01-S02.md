---
tags:
  - '#exec'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
body_hash: 'sha256:2de657f3459bd9c5f96365946dba249f47a6e3f411c9d55aa5360012bf416917'
step_id: 'S02'
related:
  - "[[2026-07-28-convergence-cost-plan]]"
---

# Wire the gate into the codebase indexer hashing loop and persist evidence after full, incremental, and scoped runs

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Route `CodebaseIndexer._hash_changed_paths` through the gate; add `full_membership` so the unscoped caller prunes evidence for deleted files.
- Persist gate evidence after each hashing loop; log reuse counts at debug.
- Derive the sidecar path from the code meta sidecar in `__init__`; drop the now-unused direct `hashlib` import.

## Outcome

Scoped and unscoped code hashing both answer warm unchanged files from a stat call; behavior for fresh writes is unchanged because racy evidence is never trusted.

## Notes

None.
