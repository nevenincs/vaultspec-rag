---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S03'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add a local_only RAG default and resolve effective server mode as qdrant_server and not local_only so local-only deterministically wins

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Added a `local_only` RAG default of `False`, completing the knob wired in the previous Step: it now flows through the wrapper's standard resolution chain (base override, then `VAULTSPEC_RAG_LOCAL_ONLY` env via the override map, then default) with the same falsey-string coercion every other boolean knob uses.
- Added an `effective_server_mode()` method to `VaultSpecConfigWrapper` that returns `qdrant_server and not local_only`, making local-only deterministically win over the server-mode default and giving backend-selecting callers one source of truth instead of reading `qdrant_server` directly.

## Outcome

Effective server-mode resolution is now first-class and complete at the config layer. Verified interactively across three env states: default (`qdrant_server=True`, `local_only=False`) yields `effective=True`; setting `VAULTSPEC_RAG_LOCAL_ONLY=1` yields `effective=False` even though `qdrant_server` stays `True`; and the redundant `VAULTSPEC_RAG_QDRANT_SERVER=0` also yields `effective=False`. `ruff check` and `basedpyright` on the changed source are clean. The P02 lifespan selection (`server/_lifespan.py:79`) and any other backend-selection consumer will switch from `cfg.qdrant_server` to `cfg.effective_server_mode()` in the following Phase, per plan scope.

## Notes

`effective_server_mode()` is intentionally a method rather than a cached default key so it always reflects the live values of both underlying knobs (including env overrides) at call time, with no staleness window. The asserting unit tests land in S04.
