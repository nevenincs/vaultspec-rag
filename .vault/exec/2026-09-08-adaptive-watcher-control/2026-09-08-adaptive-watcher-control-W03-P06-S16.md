---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:cd72e827eef8197d8caa78a0d61ab13f6defce5d1867664c93c27aa96e65b41e'
step_id: 'S16'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Cover create, modify, delete, rename, active-job, cooldown, cancellation, failure, and restart convergence

## Scope

- `src/vaultspec_rag/tests/integration`

## Changes

- `M` `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`
- `verify:` `uv run ruff format src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py` -> `pass`
- `verify:` `uv run pytest -q <non-service watcher recovery selections>` -> `pass`

## Notes

The two added integration selectors were blocked before collection because no ready
compatible machine-pointer service was captured. Pytest reported zero tests run and
required the runner's resident service before selecting the GPU tier; the gate was not
bypassed.
