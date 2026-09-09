---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:5df5675038aa49add52501649705a57b9a76a169a95fdbd8bfa33d410167229e'
step_id: 'S03'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Replace free watcher timing settings with validated policy bounds and compatibility mapping

## Scope

- `src/vaultspec_rag/config`

## Changes

- `M` `src/vaultspec_rag/config/_schema.py`
- `M` `src/vaultspec_rag/config/_settings.py`
- `M` `src/vaultspec_rag/config/_types.py`
- `M` `src/vaultspec_rag/tests/test_config.py`
- `verify:` `uv run --no-sync ruff format src/vaultspec_rag/config src/vaultspec_rag/tests/test_config.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/config src/vaultspec_rag/tests/test_config.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/config src/vaultspec_rag/tests/test_config.py` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_config.py -q` -> `pass`
