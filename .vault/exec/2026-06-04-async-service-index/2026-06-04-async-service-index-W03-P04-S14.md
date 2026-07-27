---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-07-27'
step_id: 'S14'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/cli/_search.py`

- Refactor `handle_search` inside `src/vaultspec_rag/cli/_search.py` to delegate the core search execution (for both `vault` and `code` types) directly to the backend facade functions `vaultspec_rag.search_vault` and `vaultspec_rag.search_codebase`.
- Remove manual model loading, Qdrant store leasing/instantiation, and GPU/linter logic from the CLI layer, making it a thin wrapper for transport and CLI rendering.

## Outcome

- Successfully refactored `handle_search` and verified CLI search command functions correctly via in-process and service-delegated paths.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
