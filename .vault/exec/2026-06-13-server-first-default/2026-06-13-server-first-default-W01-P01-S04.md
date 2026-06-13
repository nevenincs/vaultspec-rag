---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S04'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add unit tests asserting the server-mode default and the local-only override precedence across env and default resolution

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Description

- Added real-resolution unit tests asserting the flipped defaults: `qdrant_server` resolves `True`, `local_only` resolves `False`, and `effective_server_mode()` resolves `True` with no env set.
- Added precedence tests: a truthy `VAULTSPEC_RAG_LOCAL_ONLY` flips effective mode off while `qdrant_server` stays default-true; a falsey local-only value keeps server mode on; `VAULTSPEC_RAG_QDRANT_SERVER=0` disables effective mode independently of local-only; and local-only wins even when the server env knob is explicitly on.
- Added `_clear_server_mode_env` / `_restore_server_mode_env` helpers that snapshot and clear the two effective-mode env knobs around each default assertion, so an ambient env value the daemon may publish cannot mask a real regression.

## Outcome

The effective-mode contract is now pinned by real behaviour, not mocks: every test exercises the actual `VaultSpecConfigWrapper` resolution chain over real `os.environ` mutation, snapshotting and restoring env in `finally` and resetting the config singleton via the existing autouse fixture. Full module run is green (38 passed, 9 new). The pre-existing `test_qdrant_runtime.py::TestConfigKnobs` default assertion (updated in S01) still passes alongside. `ruff check` and `basedpyright` on the test file are clean.

## Notes

The tests deliberately clear the two server-mode env knobs before asserting defaults because the service lifespan publishes server-mode state into the process environment for the daemon's lifetime; without the clear, an inherited value would silently satisfy or break a default assertion and camouflage a real regression. No test asserts a tautology: each compares the resolver output against the value derived from the documented `qdrant_server and not local_only` rule, not against a captured run.
