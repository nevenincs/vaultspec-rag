---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'S04'
related:
  - "[[2026-06-09-operability-hardening-plan]]"
---

# Idempotently load the embedding model before lease in background reindex

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Confirmed `ServiceRegistry.load_model()` is idempotent: double-checked under `_lock`, returns immediately when `_model is not None` — zero-overhead on the service path.
- Added `get_registry().load_model()` as the first statement of the `_bg_run` closure inside `start_reindex_vault` (before `get_registry().lease(root)`).
- Added `get_registry().load_model()` as the first statement of the `_bg_run` closure inside `start_reindex_codebase` (before `get_registry().lease(root)`).
- Created `src/vaultspec_rag/tests/test_jobs_unit.py` with 11 `unit`-marked tests: AST regression guard asserting `load_model()` precedes `lease()` in both closures; `load_model()` idempotency via sentinel injection; basic jobs lifecycle correctness.

## Outcome

- `ruff check` and `ty check` both clean on `src/vaultspec_rag/jobs.py` and `src/vaultspec_rag/tests/test_jobs_unit.py`.
- 11/11 new unit tests pass with no GPU required.
- In-process callers of `start_reindex_vault` / `start_reindex_codebase` no longer hit `RuntimeError: EmbeddingModel not loaded`; service-path callers are unaffected (idempotent no-op).

## Notes

None.
