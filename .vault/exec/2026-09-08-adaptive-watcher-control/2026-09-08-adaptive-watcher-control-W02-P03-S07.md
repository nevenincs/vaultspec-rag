---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:89ec2403bc701031df1e9f432a2d93a62700a6e1947fe4f860e34ac4f365ce41'
step_id: 'S07'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Implement earliest-deadline admission with rotating root and source ties

## Scope

- `src/vaultspec_rag/watcher_admission.py`

## Changes

- `A` `src/vaultspec_rag/watcher_admission.py`
- `A` `src/vaultspec_rag/tests/test_watcher_admission.py`
- `A` `.vault/exec/2026-09-08-adaptive-watcher-control/2026-09-08-adaptive-watcher-control-W02-P03-S07.md`
- `M` `.vault/plan/2026-09-08-adaptive-watcher-control-plan.md`
- `M` `.vault/index/adaptive-watcher-control.index.md`
- `verify:` `uv run --no-sync ruff format src/vaultspec_rag/watcher_admission.py src/vaultspec_rag/tests/test_watcher_admission.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/watcher_admission.py src/vaultspec_rag/tests/test_watcher_admission.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/watcher_admission.py src/vaultspec_rag/tests/test_watcher_admission.py` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_watcher_admission.py` -> `pass`
