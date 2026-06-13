---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-09'
step_id: 'S12'
related:
  - '[[2026-06-09-operability-hardening-plan]]'
---

# Flatten `server service` nesting — lift lifecycle commands to `server`

## Scope

- `src/vaultspec_rag/cli/_app.py`
- `.vaultspec/rules/rules/vaultspec-rag.builtin.md`
- `src/vaultspec_rag/tests/test_cli.py`
- `src/vaultspec_rag/tests/test_cli_warmup.py`
- `src/vaultspec_rag/tests/test_cli_watcher.py`
- `src/vaultspec_rag/tests/integration/test_service_state.py`
- `src/vaultspec_rag/tests/integration/test_service_logs.py`
- `src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `src/vaultspec_rag/tests/integration/test_ecosystem_integration.py`
- `src/vaultspec_rag/service.py` (docstring only)
- `src/vaultspec_rag/server/_lifecycle.py` (comment only)
- `src/vaultspec_rag/server/_state.py` (comment only)

## Description

**Wiring change (`_app.py`):**
The `server_app` (previously the `"service"` sub-Typer under `server_root_app`) is now
aliased to `server_root_app` itself. The `add_typer(server_app, name="service")` call is
removed; `mcp_app`, `server_projects_app`, and `server_watcher_app` are added directly
to `server_root_app`. Because all lifecycle command modules (`_service_lifecycle.py`,
`_service_info.py`, `_service_jobs.py`, `_service_logs.py`) import `server_app` from
`_app.py` and register `@server_app.command(...)` decorators, the alias propagates the
flattening transparently — no changes to any command-function module were required.
`server_root_app`'s help text is updated to reflect the merged surface.

**Rule update (`.vaultspec/rules/rules/vaultspec-rag.builtin.md`):**
All `server service <cmd>` CLI examples in the auto-reindex section, the Server
management code block, the MCP tool mirror descriptions, and the Entry Points section
are rewritten to `server <cmd>`. `server mcp` lines are untouched.

**Test updates:**
Every `runner.invoke(app, ["server", "service", ...])` call across seven test files is
updated to the flattened `["server", ...]` form. The `server service --help` parity
assertions are updated to `server --help`. Docstring references updated to match.
Three source-file comments (`service.py`, `server/_lifecycle.py`, `server/_state.py`)
referring to the old CLI path are also corrected.

**New unit test (`TestServerRoutingFlattened` in `test_cli.py`):**
Six `unit`-marked tests using Typer `CliRunner` verify the new routing:

- `server start --help` → exit 0
- `server status --help` → exit 0
- `server watcher status --help` → exit 0
- `server projects list --help` → exit 0
- `server mcp start --help` → exit 0
- `server service --help` → exit non-zero (removed path)

## Outcome

- `ruff check` clean on all modified files.
- `ty check` clean on `_app.py` and `test_cli.py`.
- `grep -rn "server service" src/vaultspec_rag/ .vaultspec/` returns zero source matches.
- `TestServerRoutingFlattened`: 6/6 pass.
- `TestServerCommands` + `test_cli_watcher.py` (16 tests): 16/16 pass.
- Combined 22-test run: 22 passed, 0 failed.
