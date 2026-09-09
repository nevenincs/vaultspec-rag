---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:8559a0b77204d2a53c62a7c70676e0bfb6bfa52bcb712d7550644a41ff0a5bcb'
step_id: 'S09'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Expose immutable job, search, GPU, storage, limiter, and quiesce measurement snapshots to admission

## Scope

- `src/vaultspec_rag/server`

## Changes

- `A` `src/vaultspec_rag/server/_watcher_measurements.py`
- `A` `src/vaultspec_rag/tests/test_watcher_measurements.py`
- `verify:` `uv run --no-sync ruff format src/vaultspec_rag/server/_watcher_measurements.py src/vaultspec_rag/tests/test_watcher_measurements.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/server/_watcher_measurements.py src/vaultspec_rag/tests/test_watcher_measurements.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/server/_watcher_measurements.py src/vaultspec_rag/tests/test_watcher_measurements.py` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_watcher_measurements.py -q` -> `pass`
