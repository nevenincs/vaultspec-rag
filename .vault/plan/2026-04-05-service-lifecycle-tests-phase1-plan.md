---
tags:
  - '#plan'
  - '#service-lifecycle-tests'
date: 2026-04-05
modified: '2026-06-30'
related:
  - '[[2026-04-05-service-lifecycle-tests-adr]]'
  - '[[2026-04-05-service-lifecycle-tests-research]]'
  - '[[2026-04-02-service-graph-code-review-audit]]'
---

# `service-lifecycle-tests` `phase-1` plan

Integration tests for service daemon lifecycle functions — closes
TESTGAP-001/002/003/004/005/009 from the service-graph audit. All tests
exercise real subprocesses, real GPU, real Qdrant. No mocks.

## Proposed Changes

Create `src/vaultspec_rag/tests/integration/test_service_lifecycle.py` with
7 integration tests and supporting fixtures per ADR decisions D1-D6. Inline
helpers for ephemeral port allocation, health polling, and process cleanup.
Reuse existing `clean_config` fixture from `conftest.py` for config reset.

Typer CLI runner note: commands are nested at
`app` -> `["server", "service", "start|stop|status"]`. Tests invoke via
`CliRunner().invoke(app, ["server", "service", "<cmd>", ...])` or invoke
the `service_app` sub-app directly.

## Tasks

- Phase 1: Infrastructure and fixtures

  1. Create `test_service_lifecycle.py` with `@pytest.mark.integration` marker
  1. Implement `_get_ephemeral_port()` helper — bind socket to port 0, return
     assigned port (ADR D2)
  1. Implement `_poll_health(port, timeout=60)` helper — exponential backoff
     loop calling `_health_probe()`, returns health dict or raises
     `TimeoutError` (ADR D3)
  1. Implement `_service_env(tmp_path)` context manager — sets
     `VAULTSPEC_RAG_STATUS_DIR` to tmp dir, leverages `clean_config` fixture
     pattern for config singleton reset (ADR D1)
  1. Implement `_wait_for_exit(pid, timeout=10)` helper — polls
     `_is_pid_alive()` until False or timeout

- Phase 2: Core lifecycle tests

  1. `test_start_health_stop` — spawn via `_spawn_service()`, poll health,
     assert JSON has `status`, `cuda`, `models_loaded`, `uptime_s` keys,
     terminate via `_terminate_pid()`, assert process exits
  1. `test_start_already_running` — spawn service on ephemeral port, then
     invoke `service_start` via `CliRunner` on the same port, assert output
     contains "already in use"
  1. `test_stale_pid_recovery` — write `service.json` with PID 99999 (dead),
     invoke `service_start` via `CliRunner`, assert service starts fresh with
     new PID
  1. `test_stop_when_not_running` — invoke `service_stop` via `CliRunner`
     with no status file present, assert output contains "not running"
  1. `test_stop_running_service` — spawn service, invoke `service_stop` via
     `CliRunner`, verify PID is dead and `service.json` is removed. Closes
     TESTGAP-004.
  1. `test_service_status_running` — spawn service, invoke `service_status`
     via `CliRunner`, verify output contains PID, port, "running", health
     fields. Closes TESTGAP-005.

- Phase 3: Multi-project isolation test

  1. `test_multi_project_search_isolation` — spawn service, use
     `build_multi_project_fixture()` to create 2 project roots with distinct
     corpora, connect MCP `ClientSession` via `streamable_http_client`, call
     `reindex_vault` for each root, call `search_vault` with a needle from
     project-0, assert results contain project-0 needle and not project-1
     needles, repeat for project-1 (ADR D5)

- Phase 4: Validation

  1. Run `uv run pytest src/vaultspec_rag/tests/integration/test_service_lifecycle.py -v`
  1. Run `uv run ruff check src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
  1. Run full CI suite to verify no regressions

## Parallelization

Phase 1 tasks are sequential (each builds on prior). Phase 2 tests are
independent but must run sequentially (shared GPU, port resources). Phase 3
depends on Phase 1 infrastructure. Phase 4 is sequential validation.

No sub-agent parallelization — this is a single-file implementation best done
in one pass.

## Verification

- All 7 tests pass on real hardware (RTX 4080, Windows)
- No orphaned processes after test suite completes
- No ruff violations
- TESTGAP-001 (`_terminate_pid`), TESTGAP-002 (`_spawn_service`),
  TESTGAP-003 (`service_start`), TESTGAP-004 (`service_stop` happy path),
  TESTGAP-005 (`service_status` running), TESTGAP-009 (multi-project MCP)
  are closed
- Full CI test suite passes with no regressions
