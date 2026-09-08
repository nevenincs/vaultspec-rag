---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:66b0c8be3e9f4742c4bde8358beae0a0dcc481c57aaf2b7f6a8ffb07c749eb2f'
step_id: 'S10'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Replace fixed-timing slot reconciliation with durable controller collection and decisions

## Scope

- `src/vaultspec_rag/watcher_intake.py`

## Changes

- `M` `src/vaultspec_rag/watcher_intake.py`
- `A` `src/vaultspec_rag/tests/test_watcher_controller_intake.py`
- `M` `src/vaultspec_rag/tests/integration/test_document_watcher.py`
- `A` `.vault/exec/2026-09-08-adaptive-watcher-control/2026-09-08-adaptive-watcher-control-W02-P04-S10.md`
- `M` `.vault/plan/2026-09-08-adaptive-watcher-control-plan.md`
- `M` `.vault/index/adaptive-watcher-control.index.md`
- `verify:` `uv run ruff format src/vaultspec_rag/watcher_intake.py src/vaultspec_rag/tests/test_watcher_controller_intake.py src/vaultspec_rag/tests/integration/test_document_watcher.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/watcher_intake.py src/vaultspec_rag/tests/test_watcher_controller_intake.py src/vaultspec_rag/tests/integration/test_document_watcher.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/watcher_intake.py src/vaultspec_rag/tests/test_watcher_controller_intake.py src/vaultspec_rag/tests/integration/test_document_watcher.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_watcher_controller_intake.py src/vaultspec_rag/tests/test_watcher_quiesce_intake.py src/vaultspec_rag/tests/test_watcher_controller.py src/vaultspec_rag/tests/test_watcher_scheduler.py src/vaultspec_rag/tests/test_watcher_durable_scope.py` -> `pass`
- `verify:` `uvx vaultspec-core vault check all` -> `pass`

## Notes

The focused integration module could not enter its GPU-tier runner because no resident
machine-pointer service was available; equivalent classification cases and the CPU-only
intake/controller lifecycle ran in the focused unit suite.
