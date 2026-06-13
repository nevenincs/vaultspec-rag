---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S18'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Add GPU tests covering narrowed lock holds, cache behavior, and sparse conversion parity

## Scope

- `src/vaultspec_rag/tests`

## Description

- Add `test_encode_hygiene_unit.py`: sparse conversion parity (dense, COO,
  CSR, all-zero) and query-cache behavior (round trip, LRU eviction,
  surface keys, concurrent hammering).

## Outcome

9 unit tests green; full GPU integration sweep after the wave: 51 passed.

## Notes
