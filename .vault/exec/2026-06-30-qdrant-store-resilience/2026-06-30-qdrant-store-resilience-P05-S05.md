---
tags:
  - '#exec'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
body_hash: 'sha256:1a219668b5cac432127a4cee8f8d71ecf1de22b010ae23f4c17f97957ee34e96'
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
