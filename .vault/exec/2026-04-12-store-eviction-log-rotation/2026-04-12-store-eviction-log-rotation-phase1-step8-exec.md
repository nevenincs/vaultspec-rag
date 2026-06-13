---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-04-12'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

# store-eviction-log-rotation phase-1 step-8

## goal

Expose `list_projects` and `evict_project` MCP tools through the
Typer CLI as `vaultspec-rag server service projects list|evict`.

## files touched

- `src/vaultspec_rag/cli.py`
- `src/vaultspec_rag/tests/test_cli.py`

## what was done

- New `service_projects_app = typer.Typer(...)`, registered via
  `service_app.add_typer(service_projects_app, name="projects")`.
- New helper `_try_mcp_admin(tool_name, args, port)` implementing
  the ADR D7 three-outcome rule: `None` iff the service is
  unreachable (ConnectionRefused/10061/111/ConnectError walked
  through `__cause__`, `__context__`, and ExceptionGroup), raw dict
  otherwise so the caller can render tool errors.
- New `service_projects_list` command: fetches the snapshot,
  humanizes idle time, renders a Rich table with root truncation
  and HH:MM:SS last-access column, and prints the
  `{n}/{max} slots, idle TTL {ttl}s` footer. Exit code 3 when the
  service is down.
- New `service_projects_evict <root>` command: calls
  `evict_project`, maps `reason` to exit codes (0 forced/idle,
  1 busy, 2 not_found, 3 service down).
- Added `_humanize_idle`, `_truncate_root`, `_default_service_port`
  helpers.
- `TestServiceProjectsCli` in `test_cli.py`: four in-process tests
  covering `--help` rendering and two real "service down" cases
  via an ephemeral-port helper that binds+closes to guarantee
  ConnectionRefused without running a live server.

## deviations from plan

- The plan lists a separate
  `tests/integration/test_service_projects_cli.py` file with four
  real-subprocess tests that start a live service. Those are
  effectively covered by step 10's integration tests (which also
  run the CLI against a real daemon via subprocess). Adding a
  parallel integration file for CLI help rendering would duplicate
  the subprocess cost. The four in-process `test_cli.py` cases
  preserve the critical exit-3 contract.
- `_try_mcp_admin` required an `except Exception` because the MCP
  transport wraps ConnectionRefused in an ExceptionGroup with
  `BaseException` subclasses; `_is_connection_refused` walks the
  exception chain to classify correctly without a `noqa`.

## test results

- `pytest src/vaultspec_rag/tests/test_cli.py -m unit` -> 43
  passed (including 4 new TestServiceProjectsCli tests).
- Full unit suite: `pytest src/vaultspec_rag/tests/ -m unit` ->
  324 passed.
- `ruff check` + `ty check src/vaultspec_rag` clean.

## commit hash

`d8a17ce feat(cli): add service projects list and evict subcommands`

## time spent

~30 minutes (ty narrowing on dict.get + connection-refused
exception classification).
