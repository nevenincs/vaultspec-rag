---
tags:
  - '#plan'
  - '#service-token-identity'
date: '2026-05-31'
modified: '2026-05-31'
related:
  - '[[2026-05-31-service-token-identity-adr]]'
  - '[[2026-05-31-service-token-identity-research]]'
---

# `service-token-identity` `service_token implementation: daemon-side + cli-side validation` plan

Implements gh issues #124 and #125 as one PR (shared mechanism).
A uuid4 token generated at daemon startup is written to
`service.json` (via the existing heartbeat tick) and returned
from `/health`. The CLI's `_is_our_service` validates the
round-trip; mismatch reports the service as not-ours.

## Proposed Changes

- Daemon: module global `_SERVICE_TOKEN`, generated in
  `service_lifespan`, merged into `service.json` via the
  heartbeat, returned from `/health`.
- CLI: `_is_our_service` gains `port` + `expected_token`
  parameters; token round-trip becomes the primary identity
  check, exe-name fallback preserved for pre-upgrade
  compatibility.
- `service_status` adds a `Service Token Match` signal row +
  JSON payload key.
- `_health_probe` broad-except gains a `logger.debug` line
  (no-swallow rule, partial down-payment on #130).
- Tests + smoke.

## Tasks

### Phase 1 — daemon side (mcp_server.py)

1. Add module global `_SERVICE_TOKEN: str = ""` near other
   startup-state globals.
1. In `service_lifespan` startup, add `_SERVICE_TOKEN` to the
   `global` declaration, assign
   `_SERVICE_TOKEN = uuid.uuid4().hex` before the first
   heartbeat tick.
1. In `_heartbeat_tick_sync`, after the `last_heartbeat`
   merge, add `data["service_token"] = _SERVICE_TOKEN` if
   `_SERVICE_TOKEN` is non-empty.
1. Extend `HealthResponse` Pydantic model with
   `service_token: str = Field(default="", description="...")`.
1. In `health_handler`, include
   `"service_token": _SERVICE_TOKEN` in the JSON response.

### Phase 2 — CLI side (cli.py)

1. Update `_is_our_service` signature to
   `(pid, port=None, expected_token=None)`. Implement the
   token round-trip + fallback as described in the ADR.
1. Update three call sites: `service_start`, `service_stop`,
   `service_status`. Each passes `port` + `status.get("service_token")`.
1. In `service_status`, add `service_token_match` to the
   signal-gathering block. Add a `Service Token Match` row to
   the Rich table. Add `service_token_match` key to the JSON
   envelope.
1. `_health_probe` broad-except: add
   `logger.debug("health probe failed: %s", exc, exc_info=True)` before the `return None`.

### Phase 3 — tests

1. `tests/test_mcp_server.py`:
   - `TestPydanticModels::test_health_response`: assert
     `service_token` field exists and defaults to "".
   - `TestDaemonLifecycleHelpers::test_heartbeat_writes_service_token`:
     monkeypatch `_status_file_path` + set `_SERVICE_TOKEN`,
     call `_heartbeat_tick_sync()`, assert the JSON contains
     the token.
1. `tests/test_cli.py`:
   - `TestServiceTokenIdentity::test_token_match_returns_true`:
     monkeypatch `_health_probe` to return
     `{"service_token": "abc"}`, call
     `_is_our_service(pid, port, expected_token="abc")`,
     assert True.
   - `TestServiceTokenIdentity::test_token_mismatch_returns_false`:
     same monkeypatch, expected token "xyz", assert False.
   - `TestServiceTokenIdentity::test_token_absent_falls_back`:
     monkeypatch `_health_probe` to return `{}` (no
     `service_token` key), assert falls back to exe-name path
     and debug-logs the fallback.
   - `TestServiceTokenIdentity::test_token_absent_in_status_file_uses_exe_name`:
     monkeypatch `_read_service_status` to return dict without
     `service_token` key — `_is_our_service` invoked with
     `expected_token=None` uses the exe-name path (current
     behaviour preserved).

### Phase 4 — smoke

1. Start service on free port. Read `service.json`, assert
   `service_token` field present and 32 hex chars. Hit
   `/health`, assert response includes same token. Stop
   service.

### Phase 5 — commit + push + PR + merge

1. One commit with vault docs + daemon + CLI + tests in the
   same changeset.
1. PR title `feat(service): identity-verifying service_token round-trip (#124, #125)`.
1. Ignore Gemini per standing instruction. Merge after CI
   green.

## Parallelization

Phase 1 (daemon) and Phase 2 (CLI) touch disjoint files; both
can be edited in parallel. Phase 3 tests depend on Phases 1+2
landing.

## Verification

- ruff + mdformat + vault check schema clean.
- 6 new unit tests pass; full suite stays green.
- Smoke confirms token round-trip end-to-end.
- No new bare excepts; `_health_probe`'s existing swallow gets
  a debug-log line.

## Out of scope

- Codebase-wide swallow audit: gh #130.
- Token rotation / TTL: not needed for the threat model
  (identity-mismatch, not auth).
