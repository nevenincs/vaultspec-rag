---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

# store-eviction-log-rotation phase-1 step-9

## goal

Wire `install_daemon_log_rotation` into `mcp_server.main()` in the
HTTP-mode branch, between `configure_logging()` and
`uvicorn.run(...)` per ADR D1 "Install ordering (CRITICAL)".

## files touched

- `src/vaultspec_rag/mcp_server.py`

## what was done

- Added `_resolve_log_path()` helper that mirrors `cli._log_file()`
  resolution (status_dir/log_file) so the daemon writes to the same
  file the parent created on spawn.
- Inside `main(port=...)`, after argparse and before Starlette app
  construction: import `configure_logging` + `install_daemon_log_rotation`
  from `.logging_config`, call `configure_logging()`, then
  `install_daemon_log_rotation(_resolve_log_path(), max_bytes=..., backup_count=...)` using `service_log_max_bytes` / `service_log_backup_count`
  from config.
- Stdio-mode branch intentionally left untouched (stdio is
  one-shot CLI tooling, not daemon use). Explanatory comment
  cites ADR D1 by name.

## deviations

None. No unit tests added by design — coverage for this wiring
is the step-10 integration tests, per ADR D1 and the project's
no-mocks mandate.

## test results

- `ruff check` + `ty check src/vaultspec_rag` clean.
- No new unit tests; integration coverage lands in step 10.

## commit hash

`a805afc feat(mcp): install rotating log handler in daemon main`

## time spent

~10 minutes.
