---
tags:
  - '#audit'
  - '#service-lifecycle-tests'
date: 2026-04-05
related:
  - '[[2026-04-05-service-lifecycle-tests-phase1-plan]]'
  - '[[2026-04-05-service-lifecycle-tests-adr]]'
  - '[[2026-04-05-service-lifecycle-tests-phase1-exec]]'
---

# `service-lifecycle-tests` Code Review

## Test file review

### TEST-001 | PASS | No mocks/patches mandate

Zero use of mock, patch, MagicMock, monkeypatch, stubs, fakes, or unittest.

### TEST-002 | PASS | No skips mandate

No pytest.skip or @pytest.mark.skip present.

### TEST-003 | PASS | addfinalizer ordering (6 of 7 tests)

In 6 tests, `request.addfinalizer()` is registered immediately after
`_spawn_service()` returns, before any health polling or assertions.

### TEST-004 | HIGH -> FIXED | addfinalizer gap in test_stale_pid_recovery

`test_stale_pid_recovery` registered addfinalizer after `runner.invoke()`
and `_read_service_status()`. If the assertion on `new_status is not None`
failed, the spawned process would leak.

**Fix:** Defensive finalizer registered BEFORE `runner.invoke()` that reads
PID from status file at teardown time.

### TEST-005 | PASS | Port isolation, env cleanup, assertion quality

All tests allocate ephemeral ports independently. `_service_env` properly
saves/restores env vars and resets config singletons. Assertions are specific
and non-tautological.

### TEST-006 | LOW | TOCTOU race with ephemeral ports

Standard pattern. Acknowledged in ADR. No fix needed.

### TEST-007 | INFO | \_poll_health timeout 90s vs ADR 60s

Conservative deviation. Makes tests more resilient to slow GPU loads.

## Production code review

### PROD-001 | CRITICAL -> FIXED | MCP session manager not initialized

Starlette `Mount` does NOT propagate lifespan to sub-apps. The inner
`streamable_http_app()` lifespan (which starts the session manager) never
fired. All HTTP requests to `/mcp` returned 500.

**Fix:** Added `async with mcp.session_manager.run()` in `service_lifespan`.
Also set `mcp.settings.streamable_http_path = "/"` so the effective client
URL is the cleaner `/mcp` instead of `/mcp/mcp`.

### PROD-002 | HIGH -> FIXED | Double streamable_http_path

The inner Starlette app had route at `/mcp`, mounted at `/mcp`, giving
`/mcp/mcp`. Set `streamable_http_path = "/"` so the inner route is at `/`
and the effective path is `/mcp`.

### PROD-003 | LOW | Backward compatibility

The endpoint URL was always broken (500 on any path), so no existing callers
could have been using it. The fix makes it work for the first time. CLI
fast-path URLs in `cli.py` restored to `/mcp`.

### PROD-004 | MEDIUM | GPU cleanup if session_manager.run() fails

If `session_manager.run().__aenter__()` raises, the inner `finally` block
(watchers + registry) is skipped. Mitigated by the outer `finally` in
`main()` which calls `_registry.close_all()`. Watchers would not be stopped
in this edge case. Acceptable — session manager startup failure is
catastrophic and rare.

### PROD-005 | LOW | Shutdown ordering correct

Shutdown sequence: watchers stop -> registry closes -> session manager exits.
Application resources cleaned before transport layer. Sound design.

## Summary

| Severity | Found | Fixed | Open |
| -------- | ----- | ----- | ---- |
| CRITICAL | 1     | 1     | 0    |
| HIGH     | 2     | 2     | 0    |
| MEDIUM   | 1     | 0     | 1    |
| LOW      | 3     | 0     | 3    |
| INFO     | 1     | 0     | 1    |

All CRITICAL and HIGH issues fixed. 7/7 tests pass. 399 existing tests pass
(0 regressions).
