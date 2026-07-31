---
tags:
  - '#adr'
  - '#service-token-identity'
date: '2026-05-31'
modified: '2026-07-30'
related:
  - '[[2026-05-31-service-token-identity-research]]'
  - '[[2026-07-24-service-quiesce-adr]]'
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

The original implementation stored that token and the service's
discovery port in reassignable module globals. Authenticated in-process
route and lifecycle proof then had only two choices: start the full
daemon, which initializes Qdrant and GPU models, or assign production
globals from test code. Neither is an acceptable test boundary. Route
authentication, registry ownership, and the listen/discovery identity
therefore need one production app-scoped initialization seam that
remains available when the resource-owning lifespan is deliberately
absent or fails before model startup.

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
  remains the token source.
- The service port is both the loopback Uvicorn binding and the port
  published through lifecycle discovery. One immutable runtime value
  must supply both so discovery cannot advertise a different endpoint
  from the production daemon's configured listener.
- `2026-07-24-service-quiesce-adr` requires CPU-only authenticated
  production-route proof without service, Qdrant, model, or GPU
  startup. The route host still needs the real token gate and the real
  `ServiceRegistry`.
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
- The route runtime is immutable after app construction. It requires
  a non-empty token, a real `ServiceRegistry`, and a service port in
  the valid TCP range; missing or invalid app state fails closed.
- The standalone daemon remains loopback-only. App-scoped injection
  does not create a command-line, environment, network, or test-mode
  override for token, registry, or port ownership.
- Tests may omit the resource-owning lifespan only when they construct
  the same production route app with an explicit runtime. They must
  not assign server globals, start the service, or initialize Qdrant,
  models, Torch, or CUDA.

## Implementation

### Daemon side

- Add an immutable, slotted `ServerRouteRuntime` with
  `service_token: str`, `registry: ServiceRegistry`, and `port: int`.
  Validate the non-empty token and the positive, in-range port when
  constructing it.
- Add one typed request resolver for the runtime stored on the
  Starlette app. The resolver rejects absent or invalid state rather
  than consulting a fallback global.
- Add one production HTTP app factory that installs the runtime and
  builds the exact health and route table. The standalone daemon calls
  it with `uuid.uuid4().hex`, the canonical `get_registry()` result,
  the requested service port, and `service_lifespan`. The same runtime
  port is passed to Uvicorn's loopback binding.
- `service_lifespan`, heartbeat publication, health, authentication,
  and lifecycle writers consume the installed runtime or its explicit
  identity. Discovery publishers retain the runtime and publish its
  port rather than consulting process state. Every route-side registry
  read consumes the same runtime registry. Non-route service
  components may continue to use the canonical registry singleton
  because production installs that exact object in the runtime.
- Remove `_SERVICE_TOKEN` and `_service_port` from server state and
  package exports. Do not retain compatibility aliases, setters,
  forwarding shims, or fallback globals.
- In `_heartbeat_tick_sync`, after the existing
  `last_heartbeat` merge, add
  `data["service_token"] = runtime.service_token` when the token is
  non-empty (guard against the initial empty state).
- Extend `HealthResponse` with
  `service_token: str = Field(default="", description="...")`.
- In `health_handler`, include
  `"service_token": runtime.service_token` in the response dict.

### In-process route hosts

- Call the same HTTP app factory with an explicit
  `ServerRouteRuntime` and no lifespan. This hosts the exact
  authenticated production routes without starting resource
  initialization.
- Use a known non-empty token, a valid explicit port, and a real
  isolated `ServiceRegistry`. The app runtime, not test-owned global
  assignment, selects the authenticated identity, registry, and
  lifecycle publication port.
- Real loopback Uvicorn remains available when a transport or CLI
  consumer requires HTTP. Direct route proof may use the same app
  in-process.

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

App-scoped immutable ownership keeps that identity authoritative
without coupling route construction to GPU and storage startup. One
runtime supplies authentication, registry access, and the
listen/discovery port for the whole application, so concurrent route
hosts cannot overwrite each other's process globals and the shipping
daemon cannot publish a port different from the value it passes to
Uvicorn. The same production app factory prevents a test-specific
wrapper from becoming a second route contract.

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
- Authenticated route tests can use real production routes and a real
  isolated registry without mutating module state or launching the
  resource-owning lifespan.
- CPU-only lifecycle tests can use the same isolated app runtime and
  reach a real pre-model startup refusal without assigning a discovery
  port global.
- Route handlers gain an explicit runtime dependency. Adding a route
  that reads token or registry state now requires the typed request
  resolver rather than a package global.
- The module-global `_SERVICE_TOKEN` and `_service_port` interfaces are
  removed directly. Callers that assigned either must migrate to the
  HTTP app factory and its runtime.
- Pre-upgrade compatibility: old daemons + new CLI work via
  exe-name fallback. Old CLI + new daemon ignores the new
  fields. No coordinated upgrade required.
- `_health_probe` gains a debug log line — partial down-payment
  on gh #130. Full sweep stays scoped to that PR.

## Considered options

- **Selected:** immutable app-scoped route runtime installed by one
  production HTTP app factory. It preserves process identity and one
  authoritative loopback listen/discovery port while separating route
  hosting from resource startup.
- **Not selected:** a production setter or context manager around
  `_SERVICE_TOKEN`, `_service_port`, or `_registry`. It still mutates
  process-wide authority, permits concurrent hosts to interfere, and
  converts prohibited test assignment into a differently named
  assignment.
- **Not selected:** a separate port argument on the app factory or
  lifecycle publisher. It splits binding and publication ownership
  across values that can drift.
- **Not selected:** a test-only app wrapper, environment switch, or
  authentication bypass. Each creates a second route contract or
  weakens the production gate.
- **Not selected:** running `service_lifespan` in route tests. It
  starts resource owners that the CPU-only test boundary excludes.
- **Not selected:** approaches that conflict with those recorded constraints.
