---
tags:
  - '#adr'
  - '#service-lifecycle-tests'
date: 2026-04-05
modified: '2026-04-05'
related:
  - '[[2026-04-05-service-lifecycle-tests-research]]'
  - '[[2026-04-02-service-graph-code-review-audit]]'
---

# `service-lifecycle-tests` adr: integration test strategy | (**status:** `accepted`)

## Problem Statement

`_spawn_service()`, `_terminate_pid()`, and `service_start()` have zero test
coverage (TESTGAP-001/002/003 from the service-graph audit). These manage real
OS subprocesses with GPU model loading and require integration tests against
real hardware. No mocks, patches, or stubs are permitted.

## Considerations

- Project testing mandates prohibit all mocking. Tests must exercise real
  subprocesses with real GPU inference.
- Tests must not interfere with a user's running service or leave orphaned
  processes. All state must be confined to temp directories.
- GPU model loading takes ~15-30s when HF cache is warm (RTX 4080).
- TESTGAP-009 requires proving `project_root` parameter isolates search
  results across projects.
- Platform is Windows with `CREATE_NEW_PROCESS_GROUP` subprocess flags.

## Constraints

- Each test spawns a real subprocess loading ~1.9GB GPU models — tests must
  run sequentially.
- Ephemeral port allocation has a small TOCTOU race between socket release
  and service bind; mitigated by per-test port allocation.
- `service_start()` is a Typer command that raises `typer.Exit` on failure.
- On Windows, `Process.terminate()` is immediate kill — `CTRL_BREAK_EVENT`
  must be sent first for graceful uvicorn shutdown.

## Implementation

**D1: Environment-variable isolation** — Set `VAULTSPEC_RAG_STATUS_DIR` to
per-test temp dirs via `os.environ`. The spawned subprocess inherits these,
confining all state files. Reset `get_config()` singletons in teardown.

**D2: Ephemeral port via bind-to-zero** —
`socket.bind(('127.0.0.1', 0))`, read assigned port, close socket, pass port
to service. Each test gets a unique port.

**D3: Exponential backoff health poll** — Initial 0.5s, 2x multiplier, max
5s, 60s hard deadline. Uses existing `_health_probe()`. Tuned for GPU loading
time (seconds, not milliseconds).

**D4: `addfinalizer` for cleanup (not yield)** — Register
`_terminate_pid(pid)` via `request.addfinalizer()` immediately after
`_spawn_service()`. Guarantees cleanup even if fixture setup fails before
yield. Industry-standard pattern from pytest-docker, pytest-xprocess.

**D5: MCP SDK client for multi-project test** —
`streamable_http_client` + `ClientSession` + `call_tool()`. The
streamable-HTTP transport uses SSE, making raw JSON-RPC infeasible. Pattern
already proven in `cli.py` lines 575-664.

**D6: Direct function calls for tests 1-4** — Call `_spawn_service()`,
`_terminate_pid()`, `_health_probe()`, `_is_pid_alive()` directly. For
`service_start()` and `service_stop()`, use `typer.testing.CliRunner`.

## Five test cases

- **test_start_health_stop**: Spawn, poll health, verify JSON fields,
  terminate, verify process exits.
- **test_start_already_running**: Start service, attempt second start on same
  port, verify "already in use" rejection.
- **test_stale_pid_recovery**: Write `service.json` with dead PID, call
  `service_start`, verify cleanup and fresh start.
- **test_stop_when_not_running**: Call `service_stop` with no status file,
  verify graceful "not running" message.
- **test_multi_project_search_isolation**: Start service, index two corpora
  via MCP `reindex_vault`, search each, verify no cross-contamination.

## Rationale

Environment-variable isolation uses the config system's existing override
mechanism, requires zero test-only code in production, and works identically
on Windows and Unix. `addfinalizer` over `yield` is the critical pattern —
if fixture setup fails after `Popen` but before `yield`, the teardown block
never runs, leaving orphan processes that hang CI runners. The MCP SDK client
tests the full HTTP+SSE transport stack end-to-end. Direct function calls
avoid CLI parsing overhead while exercising real code paths.

## Consequences

- ~60-90s added to CI wall time (sequential subprocess spawning with GPU).
- `addfinalizer` pattern prevents orphaned processes in CI.
- No new dependencies — `mcp` client already in the project dependency tree.
- Flaky-test risk from port reuse mitigated by per-test ephemeral ports and
  explicit wait-for-exit loops after termination.
