---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:259a16efa7449a2abc43bbab4c6fb427b12d0b975c921b06dddaa18b805b65b0'
step_id: 'S05'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Make event merge, admission fencing, settlement, and cancellation handoff atomic

## Scope

- `src/vaultspec_rag/watcher_durability.py`

## Changes

- `M` `src/vaultspec_rag/watcher_retry.py`
- `M` `src/vaultspec_rag/watcher_durability.py`
- `A` `src/vaultspec_rag/tests/test_watcher_durable_scope.py`
- `A` `.vault/exec/2026-09-08-adaptive-watcher-control/2026-09-08-adaptive-watcher-control-W01-P02-S05.md`
- `M` `.vault/plan/2026-09-08-adaptive-watcher-control-plan.md`
- `M` `.vault/index/adaptive-watcher-control.index.md`
- `verify:` `uv run --no-sync ruff format src/vaultspec_rag/watcher_retry.py src/vaultspec_rag/watcher_durability.py src/vaultspec_rag/tests/test_watcher_durable_scope.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/watcher_retry.py src/vaultspec_rag/watcher_durability.py src/vaultspec_rag/tests/test_watcher_durable_scope.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/watcher_retry.py src/vaultspec_rag/watcher_durability.py src/vaultspec_rag/tests/test_watcher_durable_scope.py` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_watcher_durable_scope.py src/vaultspec_rag/tests/test_watcher_retry.py` -> `pass`
