---
tags:
  - '#exec'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
step_id: 'S01'
related:
  - "[[2026-06-21-service-first-search-fallback-plan]]"
---

# Add a local-mandate resolver (explicit --allow-fallback or configured local-only mode)

## Scope

- `src/vaultspec_rag/cli/_search.py`

## Description

- Add `_local_only_configured()` reading `VAULTSPEC_RAG_LOCAL_ONLY` (truthy unless a falsey literal) then the persisted local-only marker.
- Add `_local_search_mandated(allow_fallback)` returning True only for an explicit per-call flag or configured local-only mode.

## Outcome

Resolver lands in `src/vaultspec_rag/cli/_search.py`; unit tests assert the env/flag/marker matrix.

## Notes

Env var name sourced from the `EnvVar.LOCAL_ONLY` enum to avoid string drift.
