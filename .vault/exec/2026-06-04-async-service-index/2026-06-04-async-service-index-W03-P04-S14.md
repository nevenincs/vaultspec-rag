---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-06-04'
step_id: 'S14'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

# Refactor in-process search CLI to use public backend API search functions

## Scope

- `src/vaultspec_rag/cli/_search.py`

## Description

- Refactor `handle_search` inside `src/vaultspec_rag/cli/_search.py` to delegate the core search execution (for both `vault` and `code` types) directly to the backend facade functions `vaultspec_rag.search_vault` and `vaultspec_rag.search_codebase`.
- Remove manual model loading, Qdrant store leasing/instantiation, and GPU/linter logic from the CLI layer, making it a thin wrapper for transport and CLI rendering.

## Outcome

- Successfully refactored `handle_search` and verified CLI search command functions correctly via in-process and service-delegated paths.

## Notes
