---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S14'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Extend stress tests to assert cross-collection concurrency and same-collection exclusion semantics

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`

## Description

- Rework the store serialization tests to per-collection semantics: same
  collection waits, the other collection proceeds (new cross-collection
  non-blocking test); update the stress test lock handle.

## Outcome

44 store/chunking unit tests green, including the new
code-search-proceeds-while-vault-lock-held assertion.

## Notes
