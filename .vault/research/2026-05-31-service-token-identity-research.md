---
tags:
  - '#research'
  - '#service-token-identity'
date: '2026-05-31'
related: []
---

# `service-token-identity` research: `pid and health identity verification via service_token round-trip`

## Trigger

Two coupled gaps from #113's audit, filed as gh issues #124 and
#125 during the end-of-Wave-2 honest accounting:

- **#124**: `_is_our_service(pid)` (`cli.py`) checks only the
  process executable name (`"python" in path.lower()` on Windows,
  `"vaultspec_rag" in /proc/{pid}/cmdline` on Linux). Any Python
  process at a recycled PID passes on Windows. Long-running
  systems and crash-loop conditions hit PID reuse; `service status` reports `running / PID Matches Service: yes` for an
  unrelated process.

- **#125**: `_health_probe(port)` accepts any 200 response. If
  the daemon crashes and a different HTTP server binds the port,
  `service status` reports `Health: ready` against that
  unrelated service.

Both surfaces lie about identity. A one-shot token round-trip
closes both with one mechanism.

## Method

Sonnet design pass over the worktree (already done at design
time). This research records the file:line evidence and the
chosen integration points.

## Findings

### Daemon-side anchor points

`mcp_server.py`:

- Module globals around line 50 (`_start_time`,
  `_shutdown_recorded`, `_HEARTBEAT_INTERVAL_SECONDS`,
  `_HEARTBEAT_STALENESS_SECONDS`). New `_SERVICE_TOKEN: str = ""`
  slots in alongside.
- `service_lifespan` startup block: the `global _start_time, _shutdown_recorded` declaration is the natural place to also
  declare `_SERVICE_TOKEN` and assign
  `_SERVICE_TOKEN = uuid.uuid4().hex` at startup. The immediate
  `_heartbeat_tick_sync()` call that already fires before
  `yield` (Wave 2 #113) propagates the token into `service.json`
  on the first write — no separate startup write needed.
- `_heartbeat_tick_sync`: already reads the JSON, merges
  `last_heartbeat`, writes atomically via `.tmp` + `os.replace`.
  The token merge is one extra line:
  `data["service_token"] = _SERVICE_TOKEN` (guarded against the
  initial empty-string state so a stale token never overwrites
  a live one).
- `HealthResponse` model: extending with
  `service_token: str = ""` is an additive change. Pre-upgrade
  clients ignore the new field.
- `health_handler`: emits the model — needs one new key.

### CLI-side anchor points

`cli.py`:

- `_read_service_status` already validates `pid` + `port` only;
  `service_token` is an optional `.get()` returning `None` for
  old files. No schema breakage.
- `_is_our_service(pid: int)` (around line 1878) currently
  checks executable name only. New signature:
  `_is_our_service(pid: int, port: int | None = None, expected_token: str | None = None) -> bool`. When `port` and
  `expected_token` are both supplied: probe `/health`, compare
  tokens. Mismatch → False. Token absent in response → fall
  back to the executable-name check (pre-upgrade daemon).
- `_health_probe(port: int)` currently accepts any 200. Stays
  unchanged — token validation lives in `_is_our_service` so
  `_health_probe` remains a pure HTTP getter. Callers that want
  the token-validated check go through `_is_our_service`.
- Call sites that currently pass only `pid`:
  - `service_status` (around line 2580+): already gathers all
    signals before rendering. Trivial to also pass `port` and
    `status.get("service_token")`.
  - `service_start` (around line 2390): bails if existing
    service is "ours". Same call-site update.
  - `service_stop` (around line 2623): same.
- New `service status` row: `Service Token Match: yes | no | absent`. JSON payload (Wave 2 #112) gains `service_token_match`.

### Schema migration

Adding `service_token` to `service.json` is forward-compatible.
`_read_service_status` only validates `pid` + `port`; extra
fields pass through. Pre-upgrade `service.json` files (or
daemons that crashed before the first heartbeat tick) lack the
field — `status.get("service_token")` returns `None`. The
fallback path in `_is_our_service` keeps the executable-name
check for that case so an upgrade does not break the running
service.

### Exception-handling note

All new code paths log on failure per
`[[feedback_no_adhoc_no_swallow]]`:

- `_is_our_service` returns False on `_health_probe` failure
  (the probe already swallows OSError/timeout). The fallback
  path emits a `logger.debug` line stating the token check fell
  through to the executable-name path.
- The daemon's `uuid.uuid4().hex` cannot fail. The token write
  reuses `_heartbeat_tick_sync`'s existing try/except (which
  Wave 2 #113 already debug-logs on the broad branch); no new
  except introduced.
- `HealthResponse` serialisation cannot fail at the new field
  (string with default). No new except introduced.

### Tests

- `test_mcp_server.py` `TestHealthResponse`: assert the new
  `service_token` field exists and defaults to "". Update the
  `health_handler` JSON test to include the field.
- `test_mcp_server.py` `TestDaemonLifecycleHelpers`: new test
  that monkeypatches `_status_file_path` to tmp + sets
  `_SERVICE_TOKEN`, calls `_heartbeat_tick_sync()`, asserts the
  written JSON contains both `last_heartbeat` and
  `service_token`.
- `test_cli.py` `TestServiceTokenIdentity`: new class.
  Monkeypatch `_health_probe` to return `{"service_token": "abc"}`. `_is_our_service(pid, port, expected_token="xyz")`
  returns False. `_is_our_service(pid, port, expected_token="abc")` returns True. `_is_our_service(pid, port, expected_token=None)` falls back to exe-name check
  (pre-upgrade).

### Smoke

Start service, read `service.json`, assert
`service_token` field present and 32 hex chars. Hit `/health`,
assert response includes same token. Stop service.

## Recommendation

Ship as one PR — the two issues share the mechanism. Splitting
would duplicate the token-write half across PRs.

The Sonnet design report already documented in the prior
session is the source of truth for line numbers; this research
captures it in the vault per the no-adhoc rule.
