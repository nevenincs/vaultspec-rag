---
tags:
  - '#research'
  - '#service-lifecycle-tests'
date: 2026-04-05
modified: '2026-06-30'
related:
  - '[[2026-04-02-service-graph-code-review-audit]]'
---

# `service-lifecycle-tests` research: integration test design for service daemon

Research into how to write real end-to-end integration tests for the service
lifecycle functions (`_spawn_service`, `_terminate_pid`, `service_start`,
`service_stop`, `service_status`) without mocks, patches, or stubs.

## Findings

### Test isolation via environment variables

The `_status_dir()` function reads `VAULTSPEC_RAG_STATUS_DIR` via
`get_config()`. The `_log_file()` reads `VAULTSPEC_RAG_LOG_FILE` relative to
status dir. The spawned subprocess inherits the parent's env, so setting these
env vars before calling `_spawn_service()` or `service_start()` redirects all
state files to a temp directory. No mocking required.

The MCP server's `_default_root()` reads `VAULTSPEC_RAG_ROOT`. Setting this
in the subprocess env controls which project root the server uses by default.

### Ephemeral port selection

`_port_is_available(port)` does a TCP bind check on `127.0.0.1:port`. For
tests, bind a socket to port 0 to get an OS-assigned free port, then close it
immediately. This is the standard ephemeral port pattern. The race window
between close and service bind is negligible for localhost tests.

### Subprocess lifecycle

`_spawn_service(port, log_path)` runs
`sys.executable -m vaultspec_rag.mcp_server --port <port>` as a detached
process. On Windows it uses `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`.
Returns PID immediately.

`_terminate_pid(pid)` sends `CTRL_BREAK_EVENT` (Windows) or `SIGTERM` (Unix),
waits 2s, then force-kills if still alive. Tests must always call this in
finally blocks.

### Health polling

`_health_probe(port)` does HTTP GET to `http://127.0.0.1:{port}/health` with
5s timeout. Returns parsed JSON dict on success, `None` on connection refused.
Tests can poll this in a loop with backoff until `status == "ready"`.

Model loading takes ~15-30s when HF cache is warm (RTX 4080). A 60s timeout
per test is conservative but safe.

### Multi-project search isolation (test 5)

The MCP server accepts `project_root` parameter on all tool calls. For HTTP
transport, tools are exposed at `/mcp` via MCP streamable-HTTP protocol.

Two approaches for invoking MCP tools from tests:

- **MCP client library**: `streamable_http_client(url)` + `ClientSession` to
  call tools via the protocol. Full MCP semantics.
- **Direct HTTP via urllib**: The `/mcp` endpoint handles JSON-RPC. Simpler
  but couples tests to transport internals.

The `build_multi_project_fixture(base, n_projects=2, docs_per_project=12)`
creates distinct project roots with non-overlapping corpora and different
seeds. Each corpus has unique `NEEDLE_*` keywords. After indexing both via
`reindex_vault` with different `project_root` values, searching for a needle
from project-0 should return results only from project-0.

### Config reset requirement

The `get_config()` singleton must be reset between tests that modify env vars.
Import `reset_config` from both `vaultspec_core.config` and
`vaultspec_rag.config` and call both in setup/teardown.

### Test structure

All 5 tests share common infrastructure:

- Find ephemeral port
- Set env vars for status_dir, log_file isolation
- Spawn service via `_spawn_service()` or `service_start()`
- Poll health until ready
- Execute test assertions
- Terminate in finally block

Tests 1-4 test CLI helper functions directly. Test 5 requires MCP client
calls through the running service's HTTP transport.

### Discovered constraint: service_start() uses typer

`service_start()` is a Typer command. It calls `console.print()` and
`console.status()` (Rich). It can be invoked programmatically via
`typer.testing.CliRunner` or by calling the underlying function directly
after constructing proper arguments. Direct function call is cleaner for
integration tests — but it calls `raise typer.Exit(code=1)` on failure, which
tests must catch.

For tests 2 and 3, the service_start flow uses `_port_is_available()`,
`_read_service_status()`, `_health_probe()`, and `_spawn_service()` — all
real function calls with real I/O. No mock surfaces needed.

### Risk: port reuse between tests

If tests run sequentially and the previous service didn't fully release the
port, the next test may fail on bind. Adding a brief wait after
`_terminate_pid()` or using a different ephemeral port per test mitigates this.

## Grounded patterns (industry best practices)

### Pattern 1: `addfinalizer` over `yield` for subprocess cleanup

When a `yield` fixture's setup raises before yielding, the teardown block
never runs — leaving orphan processes. The `request.addfinalizer(cleanup_fn)`
approach registers cleanup immediately after `Popen`, so it runs even if later
setup steps fail. This is the recommended pattern for CI where orphan processes
cause hung runners.

Sources: pytest-docker PR #33, pytest Issue #3409, pytest fixture docs.

**Impact on design:** Every fixture that calls `_spawn_service()` must register
`_terminate_pid(pid)` via `request.addfinalizer()` immediately after obtaining
the PID, before any health polling or other setup that could fail.

### Pattern 2: pytest-xprocess readiness check

The pytest-xprocess plugin (pytest-dev) defines a `ProcessStarter` with either
a `pattern` (regex on stdout) or `startup_check` callback (e.g. TCP connect).
It handles PID tracking, log capture, and recursive termination. Default 120s
timeout.

**Impact on design:** We don't need the plugin (no new deps), but should follow
its pattern: register cleanup first, then poll readiness with a callback. The
health endpoint is our `startup_check`.

### Pattern 3: Uvicorn in-process thread (not applicable here)

Uvicorn's own tests use `server.run_in_thread()` to avoid subprocesses. This
sidesteps Windows platform gaps where `Process.terminate()` is an immediate
kill with no graceful ASGI shutdown. However, our tests explicitly need to
verify `_spawn_service()`, `_terminate_pid()`, and PID-file management — so
in-process testing would defeat the purpose for tests 1-4. Test 5
(multi-project isolation) could theoretically use in-process, but consistency
with the other tests and testing the full HTTP transport stack favors
subprocess.

### Pattern 4: Exponential backoff for readiness polling

Standard across uvicorn, pytest-xprocess, and Safir:

- Initial delay: 0.05-0.5s
- Multiplier: 2x
- Max delay: 1-5s
- Hard deadline: 30-120s
- Check: TCP connect or HTTP status < 500

Our `_health_probe()` already returns parsed JSON with `status` field. Polling
with initial 0.5s (GPU loading takes seconds, not ms), max 5s, 60s deadline is
appropriate.

### Pattern 5: MCP client API (verified)

The `mcp` SDK provides:

```
async with streamable_http_client(url) as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(name, arguments_dict)
        # result.content[0].text is JSON string
        # result.isError for error detection
```

Already used in `cli.py` lines 575-664 (`_call`, `_try_mcp_search`). The
streamable-HTTP transport uses SSE for responses — raw JSON-RPC POST is not
viable without reimplementing SSE parsing. Use the SDK client.

### Pattern 6: Windows subprocess termination

On Windows, `Process.terminate()` calls `TerminateProcess` — an immediate
hard kill with no graceful drain. Our `_terminate_pid()` sends
`CTRL_BREAK_EVENT` first (which uvicorn can catch for graceful shutdown),
then falls back to force-kill after 2s. Tests should verify the process
actually exits within a reasonable window (10s) after `_terminate_pid()`.

### Pattern 7: PID file testing (from gunicorn/supervisor)

- Write PID to temp dir file after spawn
- Verify file contains valid PID (`_is_pid_alive(pid)` returns True)
- After stop, verify file is removed
- For stale PID recovery: write a bogus PID before starting, assert service
  detects and overwrites
- Always use `tmp_path` or `tmp_path_factory.mktemp()` for isolation
