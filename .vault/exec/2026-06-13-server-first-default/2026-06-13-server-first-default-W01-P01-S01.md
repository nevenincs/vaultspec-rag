---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S01'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# flip the qdrant_server default from False to True in the RAG defaults so server mode is the assumed backend

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Flipped the `qdrant_server` RAG default from `False` to `True` so the resident service assumes the supervised server backend, per the server-first-default decision.
- Reworded the default's docstring to state server mode is the assumed backend (the measured ~54x end-to-end A/B win), name `local_only` as the first-class explicit opt-out introduced later in this phase, and reframe `qdrant_server` as the redundant server-mode env knob.
- Updated the one pre-existing assertion that pinned the old default (`test_qdrant_runtime.py::TestConfigKnobs::test_defaults`) from `is False` to `is True`, since the flip directly invalidates it; left every other field assertion untouched.

## Outcome

Server mode is now the default RAG backend at the config layer. `get_config().qdrant_server` resolves to `True` with no env or override set, while the existing `VAULTSPEC_RAG_QDRANT_SERVER` env override (and the falsey-string coercion already in `_resolve_rag_default`) still lets the operator force it off. The selection-knob and effective-mode resolution that consume this default land in the following Steps. Config-knob tests pass (2 passed); `ruff check` and `basedpyright` on the changed source are clean.

## Notes

The default flip broke an existing assertion outside this Step's named scope file (`test_qdrant_runtime.py`, not `test_config.py`). I corrected the single assertion in place rather than leaving the suite red, because the break is a direct and unavoidable consequence of the in-scope change; this is a one-line truth-correction, not a scope expansion. The new local-only knob and effective-mode tests remain the responsibility of S02-S04 as planned.
