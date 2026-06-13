---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S12'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add CLI tests covering --local-only env translation, the default server-mode start, and the missing-binary loud-failure path

## Scope

- `src/vaultspec_rag/tests/test_cli_server_start.py`

## Description

- Add real-surface CLI tests for the server-first `server start` local-only opt-out, with no mocks, patches, fakes, or skips.
- Cover `--local-only` env translation through the real `_service_child_env`: `local_only=True` writes `VAULTSPEC_RAG_LOCAL_ONLY=1`, `False` writes `0`, and an unset (`None`) flag leaves an operator-set value untouched.
- Cover the default server-mode start surface: with no flags neither the local-only nor the server-mode knob is written, so the daemon resolves the server-first default through its config; and `server start --help` renders the `--local-only` flag.

## Outcome

- Five tests in `src/vaultspec_rag/tests/test_cli_server_start.py`; all pass. No daemon is spawned and the running service is never restarted or stopped (the surface is exercised via `--help` and the pure env-translation helper only). `ruff check`/`ruff format`/`ty check` clean.

## Notes

- Deviation from the plan's named scope `src/vaultspec_rag/tests/test_cli.py`: the tests live in a new file `test_cli_server_start.py` instead, because `test_cli.py` was under concurrent edit by another worker on the shared branch and a parallel earlier attempt to add the class there was lost to index contention. A new file is collision-free and keeps the coverage equivalent.
- The missing-binary loud-failure path on a default start is covered at the integration tier in `test_qdrant_server_mode.py` (W01.P02.S08), which can stage an environment with no resolvable binary; staging that at the CLI tier here would require removing the provisioned binary the live service depends on.
