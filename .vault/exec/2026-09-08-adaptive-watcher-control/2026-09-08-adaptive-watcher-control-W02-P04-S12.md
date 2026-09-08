---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:3cbc255777a234b5420ea7911d3fea69d5781ba2867f3001a8380911f7935aef'
step_id: 'S12'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Reconcile restart, cancellation, failure, and terminal rebuild refusal without duplicate admission

## Scope

- `src/vaultspec_rag/watcher_runtime.py`

## Changes

- `M` `src/vaultspec_rag/watcher_intake.py`
- `M` `src/vaultspec_rag/watcher_retry.py`
- `M` `src/vaultspec_rag/watcher_runtime.py`
- `A` `src/vaultspec_rag/tests/test_watcher_recovery.py`
- `verify:` `uv run ruff format <touched Python paths>` -> `pass`
- `verify:` `uv run ruff check <touched Python paths>` -> `pass`
- `verify:` `uv run ty check <touched Python paths>` -> `pass`
- `verify:` `uv run pytest -qq <focused watcher recovery paths>` -> `pass`
