---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S08'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add integration tests for the server-first default startup path and the local-only opt-out startup path

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`

## Description

- Added a `TestServerFirstStartupSelection` class covering the three startup-selection contracts this phase establishes, exercising real config resolution, a real on-disk store, and the real supervised-start failure with no mocks.
- `test_default_config_selects_server_mode` clears the server-mode and local-only env knobs and asserts the default config resolves `qdrant_server` true, `local_only` false, and `effective_server_mode()` true - the selection point the lifespan consults.
- `test_local_only_opt_out_opens_the_on_disk_store` sets `VAULTSPEC_RAG_LOCAL_ONLY`, asserts `effective_server_mode()` is false, then opens a real `VaultStore` in a temp dir and asserts it is in local mode (`_server_mode` false) with a real reentrant point lock rather than the server-mode null context.
- `test_missing_binary_default_path_fails_loud_and_actionable` isolates the managed status dir to an empty temp dir, points the operator-binary knob at a nonexistent path, keeps server mode the default, and asserts `start_supervised_from_config` (the call the lifespan wraps) raises a `RuntimeError` naming `server qdrant install`; it fails explicitly rather than skipping if a `qdrant` happens to resolve on `PATH`.

## Outcome

The server-first default startup path and the local-only opt-out path are now covered by real-behavior integration tests, and the loud-failure contract the lifespan depends on is pinned at its source. All three pass (3 passed in ~1.1s) with no GPU and without disturbing the running service: the local-only test opens a real on-disk QdrantLocal in a temp dir, and the failure test drives the real binary-resolution failure (`qdrant` is absent from this host's `PATH`). `ruff check` and `basedpyright` on the changed test file are clean.

## Notes

The lifespan's own wrapping of the failure into the `--local-only`-naming abort (S06) is covered at the unit-of-behavior boundary by asserting the underlying `start_supervised_from_config` failure here plus the S06 record's lint/type verification; driving the full `service_lifespan` coroutine end-to-end would load GPU models and spawn the resident daemon, which the test mandate steers away from in favour of fast real-behavior coverage of the actual decision points. The missing-binary test uses an explicit `pytest.fail` (never a skip) on the rare host where `qdrant` is on `PATH`, so the contract is never silently bypassed.
