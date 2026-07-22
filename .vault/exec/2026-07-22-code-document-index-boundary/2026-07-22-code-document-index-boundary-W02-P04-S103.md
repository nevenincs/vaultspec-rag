---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S103'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Register document indexer construction, counts, close lifecycle, and watcher injection in managed project slots

## Scope

- `src/vaultspec_rag/service.py`
- `src/vaultspec_rag/registry.py`
- `src/vaultspec_rag/server/_watcher.py`

## Description

- Construct one document indexer in every managed project slot.
- Expose model-free document counts and inject the managed indexer into watcher construction.

## Outcome

Document indexing now shares project leases, GPU serialization, store closure, and watcher lifecycle.

## Notes

Document job dispatch remains assigned to its later planned phase.
