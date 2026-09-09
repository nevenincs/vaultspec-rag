---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:4fb3eedef49fae5a1e8c58ccbc829f5c71fe9093a0b1d98ae02dc9ca4a8507f9'
step_id: 'S17'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Demonstrate bounded batch frequency, maximum freshness, fair progress, and pressure recovery under load

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`

## Changes

- `A` `src/vaultspec_rag/tests/test_watcher_load.py`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_watcher_load.py src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_watcher_load.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_watcher_load.py src/vaultspec_rag/tests/test_watcher_scheduler.py src/vaultspec_rag/tests/test_watcher_admission.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py -k "adaptive_load or load_scheduler or safety_pressure"` -> `fail`

## Notes

The resident integration selector could not collect tests because no compatible machine-pointer service was captured before pytest isolated its managed paths. The CPU-only in-process module exercises the real controller, admission arbiter, and service scheduler callbacks without mocks, stubs, sleeps, or skips.
