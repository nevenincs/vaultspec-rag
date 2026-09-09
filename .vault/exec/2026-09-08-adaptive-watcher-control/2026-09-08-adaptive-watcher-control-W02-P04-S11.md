---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:50e050e012c64bf7dda18499d877ca85425144cb70b676c1c2c259e378751520'
step_id: 'S11'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Bind controller generations to canonical watcher job creation, coalescing, and settlement

## Scope

- `src/vaultspec_rag/watcher_execution.py`

## Changes

- `M` `src/vaultspec_rag/watcher_execution.py`
- `M` `src/vaultspec_rag/watcher_intake.py`
- `M` `src/vaultspec_rag/tests/test_watcher_quiesce_intake.py`
- `verify:` `uv run ruff check src/vaultspec_rag/watcher_execution.py src/vaultspec_rag/watcher_intake.py src/vaultspec_rag/tests/test_watcher_quiesce_intake.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/watcher_execution.py src/vaultspec_rag/watcher_intake.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_watcher_controller_intake.py src/vaultspec_rag/tests/test_watcher_durable_scope.py src/vaultspec_rag/tests/test_watcher_quiesce_intake.py src/vaultspec_rag/tests/test_watcher_scheduler.py src/vaultspec_rag/tests/test_watcher_admission.py` -> `pass`
