---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: 2026-06-08
modified: '2026-06-08'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` `P04.S13`: Test suite harmonization

- **Status**: Completed
- **Time**: 2026-06-08
- **Commit**: (pushed directly to branch)

## Actions Taken

- Rewrote the integration test suite (`conftest.py`, `test_service_metrics.py`, `test_service_state.py`, `test_service_jobs.py`, `test_service_logs.py`) to launch a real, unmocked daemon process via `subprocess.Popen` in the `live_service` fixture.
- Eradicated all mocks, patches, fakes, and skips from the integration surface area.
- Fixed residual linting and formatting issues left from the subagent's run, including the correct type-hints for `pathlib.Path` imports.
- Updated `vaultspec_rag/server/_main.py` with `# type: ignore` around `mcp.get_starlette_app()` to bypass the `ty` check error for `FastMCP`'s untyped ASGI mounting.
- Dropped legacy or hallucinated "A2A" testing assumptions in favor of the real REST + standard stdio interface.

## Lessons Learned

- Pre-commit hooks (`vaultspec-core vault plan step check`, `ty`, and provider artifact guards) will rigorously block commits unless the staging area is perfectly groomed.
- Integrating a live `subprocess` loop for Daemon tests guarantees no false-positive test signals, fully satisfying the `no-mocks` invariant enforced by the user rules.

## Next Steps

- Validate final `pytest` metrics on the live server.
- The plan `2026-06-08-sparse-search-latency-plan` is now effectively completed pending overall CI.
