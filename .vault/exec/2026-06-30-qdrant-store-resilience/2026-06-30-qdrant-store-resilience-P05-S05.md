---
tags:
  - '#exec'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S05'
related:
  - "[[2026-06-30-qdrant-store-resilience-plan]]"
---

# Add real-behavior tests for quarantine move, detection parser, bounded retry, and the CLI verb under an isolated storage dir

## Scope

- `src/vaultspec_rag/tests/test_qdrant_store_resilience.py`

## Description

Real-behavior test suite, no mocks.

## Outcome

`test_qdrant_store_resilience.py`: quarantine move, detection branches, bounded retry against a real subprocess fake binary, and the CLI verb under an isolated `VAULTSPEC_RAG_QDRANT_STORAGE_DIR`.

## Notes

12 tests pass; ruff/ty/basedpyright/complexity green.
