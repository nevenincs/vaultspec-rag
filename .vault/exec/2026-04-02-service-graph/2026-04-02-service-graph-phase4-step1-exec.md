---
tags:
  - '#exec'
  - '#service-graph'
date: 2026-04-02
related:
  - '[[2026-04-02-service-graph-phase1-plan]]'
---

# service-graph phase-4 step-1: service daemon commands

## Summary

Replaced the Docker-oriented stubs in `cli.py` with functional dmypy-style
`service start`, `service stop`, and `service status` commands (D1). Added
`__main__` argparse block to `mcp_server.py` for subprocess `--port`
invocation.

## Files modified

- `src/vaultspec_rag/cli.py` -- added module-level imports (`json`,
  `signal`, `subprocess`, `time`, `contextlib`, `datetime`). Added 8
  helper functions: `_status_dir`, `_status_file`, `_log_file`,
  `_write_service_status`, `_read_service_status`, `_is_pid_alive`,
  `_health_probe`, `_spawn_service`, `_terminate_pid`. Replaced 3 stub
  commands with full implementations. Added `--port` option to
  `service start` with `VAULTSPEC_RAG_PORT` env var default (8766).
  Removed redundant local imports (`os`, `subprocess`, `sys`).

- `src/vaultspec_rag/mcp_server.py` -- added argparse `__main__` block
  accepting `--port` so subprocess invocation works via
  `python -m vaultspec_rag.mcp_server --port N`.

- `src/vaultspec_rag/tests/test_cli.py` -- updated 2 existing service
  stub tests to match new behavior (stop/status with no status file).
  Added `TestServiceDaemonHelpers` class with 10 tests covering PID
  liveness, status file round-trip, JSON validation, missing/invalid
  files, and health probe on non-listening port.

## Test results

- 38 CLI tests pass (34 in test_cli.py + 4 in test_cli_warmup.py)
- ruff check and ruff format clean
- ty type checker clean
