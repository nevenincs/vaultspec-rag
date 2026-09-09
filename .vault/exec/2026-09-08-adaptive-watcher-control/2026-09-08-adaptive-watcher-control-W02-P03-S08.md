---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:169ff1fdee2c794840d39e558d1e06ada0e2d4df5d2e7f776169b60ea2dffce0'
step_id: 'S08'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Own controller registration, deadline scheduling, wakeups, and bounded reevaluation in the service

## Scope

- `src/vaultspec_rag/server/_watcher.py`

## Changes

- `M` `src/vaultspec_rag/server/_watcher.py`
- `A` `src/vaultspec_rag/tests/test_watcher_scheduler.py`
- `A` `.vault/audit/2026-09-08-adaptive-watcher-control-s08-scheduler-audit.md`
- `A` `.vault/exec/2026-09-08-adaptive-watcher-control/2026-09-08-adaptive-watcher-control-W02-P03-S08.md`
- `M` `.vault/plan/2026-09-08-adaptive-watcher-control-plan.md`
- `M` `.vault/index/adaptive-watcher-control.index.md`
- `verify:` `uv run ruff format src/vaultspec_rag/server/_watcher.py src/vaultspec_rag/tests/test_watcher_scheduler.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_watcher.py src/vaultspec_rag/tests/test_watcher_scheduler.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_watcher.py src/vaultspec_rag/tests/test_watcher_scheduler.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_watcher_scheduler.py src/vaultspec_rag/tests/test_watcher_start_contract.py src/vaultspec_rag/tests/test_server.py -k "watcher or stop_all"` -> `pass`
- `verify:` `uvx vaultspec-core vault check all` -> `pass`
