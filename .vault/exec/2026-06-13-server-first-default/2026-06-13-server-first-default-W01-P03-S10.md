---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S10'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# translate the --local-only start flag into the VAULTSPEC_RAG_LOCAL_ONLY daemon env, leaving operator-set env untouched when unset

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

The detached daemon inherits configuration only through its environment, so the
`--local-only` start flag must be translated into the `VAULTSPEC_RAG_LOCAL_ONLY`
daemon env var the same way the watcher flags translate to `VAULTSPEC_RAG_WATCH*`
and `--qdrant` translates to `VAULTSPEC_RAG_QDRANT_SERVER`. Added a tri-state
`local_only: bool | None` parameter to `_service_child_env` and threaded it through
`_spawn_service`. When the parameter is `None` (the operator passed no flag) nothing
is written, so an operator-exported `VAULTSPEC_RAG_LOCAL_ONLY` survives untouched;
when `True`/`False` it is written as `"1"`/`"0"` and overrides any operator-set
value. The spawned daemon's `effective_server_mode()` then resolves the on-disk
store correctly from that env var.

## Outcome

- `_service_child_env` and `_spawn_service` in `src/vaultspec_rag/cli/_process.py`
  gained the `local_only` parameter; the translation mirrors the existing watch and
  qdrant tri-state semantics exactly (unset leaves operator env intact).
- Five unit tests added to `src/vaultspec_rag/tests/test_cli_service_watch.py` (the
  established home for `_service_child_env` translation tests) covering: unset adds
  no env, `True`->"1", `False`->"0", unset preserves an operator-set value, and a
  set flag overrides an operator-set value. All exercise the real pure function
  against `os.environ` with no mocks.
- `ruff check` and `basedpyright` clean on `_process.py`; 12 tests pass in
  `test_cli_service_watch.py`.

## Notes

The `__all__` export for `_service_child_env`/`_spawn_service` was already in place;
no export change needed. The daemon-side resolution (`effective_server_mode()`) is
owned by other agents (config.py landed in W01.P01).
