---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:8f7c3acfbd8140a9a8dfbc30ffb2a514fac57d93fc390c7ef24d870c4a616317'
step_id: 'S01'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Define controller state, reason, transition, measurement, scope, and snapshot models

## Scope

- `src/vaultspec_rag/watcher_controller.py`

## Changes

- `A` `src/vaultspec_rag/watcher_controller.py`
- `A` `src/vaultspec_rag/tests/test_watcher_controller.py`
- `A` `.vault/exec/2026-09-08-adaptive-watcher-control/2026-09-08-adaptive-watcher-control-W01-P01-S01.md`
- `M` `.vault/plan/2026-09-08-adaptive-watcher-control-plan.md`
- `M` `.vault/index/adaptive-watcher-control.index.md`
- `verify:` `uv run --no-sync ruff format src/vaultspec_rag/watcher_controller.py src/vaultspec_rag/tests/test_watcher_controller.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/watcher_controller.py src/vaultspec_rag/tests/test_watcher_controller.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/watcher_controller.py src/vaultspec_rag/tests/test_watcher_controller.py` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_watcher_controller.py` -> `pass`
