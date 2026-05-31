---
tags:
  - '#adr'
  - '#service-token-identity'
date: '2026-05-31'
related:
  - '[[2026-05-31-service-token-identity-research]]'
---

# `service-token-identity` adr: `uuid4 service_token written to service.json + returned from /health` | (**status:** `accepted`)

## Problem Statement

Two truth-lying surfaces in `cli.py`:

- `_is_our_service(pid)` reports True for any Python process
  at the recorded PID. A recycled PID owned by an unrelated
  python.exe passes the check on Windows; `service status`
  declares the service `running / PID Matches Service: yes`
  even though the daemon died and a different process now owns
  the PID (gh #124).

- `_health_probe(port)` accepts any HTTP 200. A crashed daemon
  whose port was rebound by another HTTP server (test fixture,
  local dev server, anything) shows `Health: ready` against the
  wrong service (gh #125).

Both close with one mechanism: a per-process token written to
`service.json` at startup and returned from `/health`. The CLI
compares them. Mismatch → the responding process is not the
one named in `service.json`.

## Considerations

- The daemon already writes `service.json` via the heartbeat
  task. Adding the token to the heartbeat payload is one line,
  no new writer.
- The CLI already reads `service.json`. Reading
  `status.get("service_token")` is one line, no schema change.
- `HealthResponse` is a Pydantic model with default-empty
  optional fields. Adding `service_token: str = ""` is
  backwards-compatible.
- Token generation runs exactly once per daemon process at
  startup, before the first heartbeat tick. `uuid.uuid4().hex`
  in `service_lifespan` startup is the right anchor.
- Pre-upgrade `service.json` files have no `service_token`.
  The CLI must tolerate token-absent and fall back to the
  existing executable-name check rather than declare "crashed".
  An upgrade that flips the running daemon's reported state
  from "running" to "crashed" because of a missing field would
  be a regression.

## Constraints

- Backwards compatibility: old daemons (no token in JSON, no
  token in `/health`) still report correctly under the new
  CLI. Old CLI against new daemon (extra field in JSON, extra
  field in `/health`) ignores the token.
- No new dependencies: `uuid` is stdlib.
- No new silent excepts. Token-mismatch returns False
  explicitly; token-absent emits a `logger.debug` line and
  falls back. Both observable per
  `[[feedback_no_adhoc_no_swallow]]`.

## Implementation

### Daemon side (`src/vaultspec_rag/mcp_server.py`)

- Add module global `_SERVICE_TOKEN: str = ""` near the other
  startup-state globals.
- In `service_lifespan` startup, declare it in the `global`
  line and assign `_SERVICE_TOKEN = uuid.uuid4().hex` early —
  before the first heartbeat tick fires.
- In `_heartbeat_tick_sync`, after the existing
  `last_heartbeat` merge, add
  `data["service_token"] = _SERVICE_TOKEN` when the token is
  non-empty (guard against the initial empty state).
- Extend `HealthResponse` with
  `service_token: str = Field(default="", description="...")`.
- In `health_handler`, include
  `"service_token": _SERVICE_TOKEN` in the response dict.

### CLI side (`src/vaultspec_rag/cli.py`)

- Change `_is_our_service(pid: int)` to
  `_is_our_service(pid: int, port: int | None = None, expected_token: str | None = None) -> bool`. When both
  `port` and `expected_token` are non-empty:
  1. Call `_health_probe(port)`.
  1. Probe returned a dict with `service_token` matching →
     return True (positively ours).
  1. Probe returned a dict with `service_token` mismatching →
     return False (positively not ours).
  1. Probe returned a dict without `service_token`
     (pre-upgrade daemon) → fall back to exe-name check.
     `logger.debug("token-absent fallback for pid=%d port=%d", ...)`.
  1. Probe returned None (network failure) → fall back to
     exe-name check.
- Update three call sites to pass `port` + `expected_token`:
  `service_start` existing-instance guard, `service_stop`
  validation, `service_status` signal gather.
- In `service_status`, add a derived `Service Token Match`
  signal alongside `PID Matches Service`. JSON payload gains
  `service_token_match: bool | None`.

### Exception-handling note

- `_health_probe`'s existing broad
  `except Exception: return None` is being touched indirectly
  in this PR. A small `logger.debug("health probe failed: %s", exc, exc_info=True)` line is added so the swallow is
  observable. Full sweep stays scoped to gh #130.
- New token-absent fallback in `_is_our_service` emits the
  debug line described above.

## Rationale

A uuid4 token is overkill for an auth threat model but the
right shape for an identity-mismatch threat model: trivially
unguessable enough that a coincident PID collision + HTTP
server on the same port cannot also coincidentally return the
same 32-hex string. Random tokens beat content-derived hashes
because the daemon's content is identical across restarts but
the token regenerates every process — exactly what reuse
detection needs.

CLI-side fallback to exe-name on token-absent (over "declare
crashed") preserves upgrade safety. Operators running
`pip install -U vaultspec-rag` against a running daemon should
not see the new CLI report the daemon as crashed.

## Consequences

- `service status` reports false negatives for unrelated HTTP
  servers / recycled PIDs. The new signal row makes the
  divergence visible; the JSON payload makes it scriptable.
- `service_token` in `service.json` is a small privacy surface
  (anyone with read on `~/.vaultspec-rag/` can see it). Not a
  credential — knowing the token grants nothing, only confirms
  identity. Acceptable trade-off.
- Pre-upgrade compatibility: old daemons + new CLI work via
  exe-name fallback. Old CLI + new daemon ignores the new
  fields. No coordinated upgrade required.
- `_health_probe` gains a debug log line — partial down-payment
  on gh #130. Full sweep stays scoped to that PR.
