---
tags:
  - '#research'
  - '#service-operability'
date: '2026-06-01'
modified: '2026-06-30'
related:
  - "[[2026-05-31-server-mcp-route-adr]]"
  - "[[2026-05-31-service-token-identity-adr]]"
  - "[[2026-05-30-service-lifecycle-adr]]"
  - "[[2026-04-02-service-graph-adr]]"
  - "[[2026-04-12-store-eviction-log-rotation-adr]]"
  - "[[2026-04-12-index-progress-bars-adr]]"
  - "[[2026-05-30-cli-json-output-adr]]"
  - "[[2026-05-28-cli-backend-parity-adr]]"
---

# service-operability research: observability + watcher-config triage

Three open issues (#142, #143, #144) were all surfaced during real production
use of the resident RAG HTTP service in a shared worktree driven by multiple
concurrent agents. They cluster around three gaps in the running service:
observability (no plain-HTTP read surfaces), watcher/auto-reindex
configurability (everything hardcoded and implicit), and the absence of a
designed, opt-out-able auto-reindex contract. This document grounds every
issue claim against the current `main` tree, reconciles them with the settled
decisions in prior service-orchestration ADRs, and proposes a triage strategy:
dependency ordering, what can ship alone, and a delivery sequence.

## Findings

### 1. Grounded current state (verified against `main`, not the cited 0.2.10)

All issue claims hold against current source, with two refinements.

- **HTTP surface is exactly two routes.** The service `Starlette` app declares
  only `Mount("/mcp", ...)` and `Route("/health", health_handler)` with
  `lifespan=service_lifespan` (in `mcp_server.py`, route table assembled inline
  in `main()`). A single ASGI wrapper rewrites `/mcp` → `/mcp/`; the prior
  `server-mcp-route` ADR mandates that future routes be added as Starlette
  `Route`s on the inner app, never as more ASGI wrappers.
- **`service_token` is identity-only, NOT an auth gate.** It is a per-process
  `uuid4` generated in the lifespan, mirrored into `service.json` and echoed by
  `/health`. There is no inbound token check anywhere — both routes are
  unauthenticated. The `service-token-identity` ADR is explicit: "not a
  credential — knowing the token grants nothing, only confirms identity." Any
  use of it to gate #142 endpoints is a **new role** for the token.
- **Watcher tuning is hardcoded literals.** `watch_and_reindex(...)` defaults
  `debounce: int = 2000` (ms) and `cooldown: float = 30.0` (s); cooldown is
  tracked per-source via `time.monotonic()` (independent vault vs code timers),
  and suppressed triggers are dropped (debug-logged, not queued). `_ensure_watcher`
  does not even pass these args, so the literals always win.
- **Watcher start is lazy/implicit, no opt-out.** `_ensure_watcher(root)` fires
  as a side-effect of the first successful `search_*`/`reindex_*` MCP tool call
  per root (double-check lock, one watcher per resolved root). The only stop
  paths are internal (project-close callback; lifespan/stdio `finally`). There
  is no tool, flag, env, or toggle to enable/disable/stop a watcher on demand.
- **`server service start` exposes only `--port`.** The daemon is launched as a
  **detached subprocess** that inherits only the parent **env** — it parses no
  argv beyond `--port`. This is the single most important plumbing fact: CLI
  flags cannot reach the daemon except by being translated into env vars on the
  child env dict before spawn.
- **Config has a clean 3-point extension pattern.** Settings live in
  `_RAG_DEFAULTS`, each paired with an `EnvVar` member and an
  `_ENV_OVERRIDE_MAP` entry; resolution is explicit-value → env → default, with
  automatic `bool`/`int`/`float` coercion driven by the default's type. The
  issue's claim that only ROOT/DATA_DIR/PORT/LOG_LEVEL env vars exist is
  **stale** — the prefix already covers ~17 keys (idle-TTL, max-projects, log
  rotation, embedding batch sizes, etc.). The accurate point: **no
  watcher-related key exists yet**, and adding three (`watch_enabled`,
  `watch_debounce_ms`, `watch_cooldown_s`) is a mechanical 3-point change.
- **No server-side job/progress state exists.** `reindex_vault`/`reindex_codebase`
  run synchronously inside the request and return a populated `IndexResponse`;
  they pass `NullProgressReporter()`, i.e. progress is explicitly discarded.
  `RichProgressReporter` is client-side only. A repo-wide search for job/task/202
  state found nothing. `/jobs` is therefore **net-new server-side machinery**,
  not an exposure of existing state — the only reusable seam is the
  `ProgressReporter` protocol.
- **Service log rotation is already wired.** Logging writes to
  `~/.vaultspec-rag/service.log` via a size-based `DaemonRotatingFileHandler`
  (default 10 MiB × 5 backups, fds 1/2 re-`dup2`'d on rollover). A `/logs`
  endpoint must read across the rotated set (`service.log`, `.log.1`, …) and
  tolerate mid-rollover races; it must preserve the grep-friendly
  `service.lifecycle event=...` tokens.
- **Multi-project state is already modeled.** A single global service shares a
  `ServiceRegistry` of project slots (lease/ref-count/idle-TTL/LRU cap); MCP
  tools `list_projects()`/`evict_project()` and a `service projects` CLI
  subcommand already exist. An HTTP `/projects` should serve the same payload
  `list_projects()` returns, and `/status` should mirror the four lifecycle
  signals `service status` already derives (JSON present / PID alive / port
  listening / heartbeat age).

### 2. Settled decisions the new work must respect (from prior ADRs)

- New HTTP routes go on the inner Starlette app as `Route`s; no second ASGI
  wrapper (`server-mcp-route`).
- An HTTP **admin/control** surface (`/admin/projects`) was previously
  **rejected** specifically as a *second control transport duplicating MCP* ("a
  second transport, a second auth boundary, a second client to maintain"). That
  rejection forbids **duplicating** control over HTTP — it does **not** mean the
  CLI should lack control. The CLI already reaches the running daemon as an **MCP
  client** through the `_try_mcp_admin(tool, args, port)` seam (used by
  `service projects list/evict`). So CLI control parity is reached by extending
  that seam (add the missing MCP tools + matching CLI subcommands), **not** by a
  parallel HTTP control API. New HTTP routes are justified only where MCP's
  structured tool protocol cannot serve — raw log-as-text and a Prometheus
  `/metrics` scrape target for non-MCP operators.
- `/health` is intentionally ungated; gating applies only to new endpoints.
- Eager model load via lifespan is settled for the HTTP service; `service.json`
  schema + 15 s heartbeat + 60 s staleness are fixed.
- Config additions follow the 3-point template; CLI parity contract = MCP param
  - CLI flag + docs in three places (`README.md`, package README, the
    `vaultspec-rag.builtin.md` rule). Discrete flags, not an options dataclass.
    `ctx.get_parameter_source(...) == DEFAULT` is the idiom for "user didn't type
    this flag."
- JSON envelope is fixed: success `{"ok": true, "command", "data"}`, error
  `{"ok": false, "error", "message", "remediation"?}`, one document per
  invocation, `ok` agreeing with exit code, reusing existing Pydantic models.
  Exit codes are a stable contract (0 running / 3 stopped / 4 divergent / 2
  usage).
- **A background sweeper/timer thread was repeatedly rejected** (eviction is
  lazy/traffic-triggered). #144's "optional scheduled full rebuild" reintroduces
  precisely that rejected pattern and must be treated as a contested,
  default-off, separately-decided item.

### 3. Per-issue analysis

**Core principle (corrected with the requester).** All three issues share one
root cause: the **CLI lacks parity with MCP for controlling and observing the
running server**. The objective is full **CLI ⇄ MCP parity over the entire
server surface** — status, logs, jobs/queue, watcher state, watcher config +
lifecycle control, projects, reindex triggering — each reachable and, where it
mutates, controllable from **both** the CLI and MCP. The CLI is the deficient
side today. This extends the established `cli-backend-parity` contract from
backend search capabilities to the **server-runtime/control** surface.

**#143 — watcher/auto-reindex configurability (smallest, foundational).**
The backend slice is a mechanical 3-point config change plus threading the
values from `_ensure_watcher` into `watch_and_reindex` (which already accepts
them) behind a `watch_enabled` guard. Because the daemon only inherits env, the
CLI `--watch/--no-watch/--watch-debounce-ms/--watch-cooldown-s` flags must be
translated to `VAULTSPEC_RAG_WATCH*` env on the child env dict before `Popen`.
Docs in the three required places complete it. No dependency on anything else.

**#144 — auto-reindex as a first-class feature (design contract for #143).**
This is the behaviour/design layer over #143: explicit lifecycle (allow eager
watcher start at `service start`, keep lazy as an option), a unified config
model, a clean opt-out (`--no-watch` / `VAULTSPEC_RAG_WATCH=0`), and an
observability hook (watcher state, surfaced per the parity principle below).
Per the parity principle, watcher **runtime control** — start / stop /
reconfigure against the running daemon, and query its state — must be exposed
through **both** a CLI subcommand and a matching MCP tool (the CLI side riding
the existing `_try_mcp_admin` seam), not only as `service start` startup env.
The contested element is the optional service-managed periodic full rebuild — it
collides with the settled "no background thread" stance and should be carved out
as default-off and decided on its own merits. #144 and #143 should be **folded
into one ADR** (design = #144, surface = #143); the issues themselves invite this.

**#142 — server state + control parity across CLI and MCP (largest).**
This is the observability+control half of the parity principle: every
server-runtime surface must be reachable from **both** the CLI and MCP. Decomposed
by transport and cost, not by "read vs write":

- *Transport decision (design, low code):* control and structured reads ride the
  existing CLI-as-MCP-client seam (`_try_mcp_admin`) — add MCP tools (e.g.
  `get_logs`, `get_jobs`, `get_watcher_state`, plus the watcher-control tools
  from #144) and matching CLI subcommands. This delivers CLI parity without a
  second control transport, honouring the prior admin-route rejection. The only
  questions left: which surfaces (if any) also get a direct HTTP route, and how
  the HTTP routes are gated (reuse `service_token` as a bearer? header vs query
  param? loopback-only binding?).
- *Tier 1 — structured state that already exists:* `status` (server + index
  state, mirroring the four `service status` signals), `projects` (the
  `list_projects()` payload), and watcher state (once #143/#144 expose it).
  Reachable via MCP tool + CLI subcommand cheaply; an HTTP mirror is optional.
- *Tier 2a — log access:* the rotated `service.log` set served as text. Wanted
  as a direct HTTP `/logs` route (MCP's structured protocol serves raw text
  poorly) **and** a `get_logs` MCP tool + CLI subcommand for parity. Must read
  across rotated files and tolerate mid-rollover races.
- *Tier 2b — jobs / queue / current-activity (the one net-new component):* today
  there is **no** server-side job/queue state — tool reindexes run synchronously
  and the watcher's background reindexes run invisibly (nothing records what is
  in-flight, pending, or cooldown-suppressed). A jobs/queue view on *either*
  surface requires first introducing a lightweight in-flight registry that the
  watcher and reindex paths write to. This was the reporter's single biggest
  blind spot — high value, most work.
- *Tier 3 — `/metrics`:* greenfield Prometheus counters for external scrapers;
  HTTP-native, no MCP equivalent needed.

### 4. Dependency graph

```
#143 backend config (FOUNDATION, no deps)
  └─> #143 CLI flags (needs env-translation seam on service start)
        └─> #144 lifecycle + runtime control parity (needs #143 config keys)
              └─> #142 watcher-state surface (needs watcher state #144 exposes)

#142 parity/transport decision (FOUNDATION for the state+control surface)
  ├─> Tier 1: status, projects, watcher-state  (MCP tool + CLI subcmd; HTTP optional)
  ├─> Tier 2a: logs  (HTTP /logs route + get_logs MCP tool + CLI subcmd)
  ├─> Tier 2b: jobs/queue  (also needs the net-new in-flight registry)
  └─> Tier 3: /metrics  (HTTP-native Prometheus, no MCP equivalent)
```

Two independent foundations: the **#143 config backend** (unblocks the watcher
control chain) and the **#142 parity/transport decision** (how each surface is
exposed on CLI + MCP, and which also get an HTTP route + gating). They are
orthogonal except where the watcher-state surface couples them.

### 5. Triage strategy — what ships alone vs lands together

- **Ships independently, immediately, lowest risk:** #143 backend config
  (env + `_RAG_DEFAULTS` + thread into watcher) — delivers opt-out and tuning
  on its own, the single most-requested production fix.
- **Lands together as one feature:** #143 + #144. The CLI flags, env, lifecycle,
  opt-out, and docs are one coherent surface backed by one ADR. Splitting them
  produces a half-configurable feature.
- **Parity, then cheap:** #142 Tier 1 (status, projects, watcher-state) — MCP
  tool + CLI subcommand over the existing `_try_mcp_admin` seam; an HTTP mirror
  is optional. Watcher-state additionally waits on #143/#144.
- **Parity, then expensive, ship last:** #142 logs (Tier 2a — HTTP route + MCP
  tool), jobs/queue (Tier 2b — needs the net-new in-flight registry), `/metrics`
  (Tier 3). Defer until the cheap surfaces prove the transport/gating model.
- **Contested, default-off, decide separately:** #144's scheduled full rebuild
  (background-thread tension).

### 6. Recommended delivery sequence

1. **ADR-A — auto-reindex contract (#144 + #143).** Decide config keys/names/
   units/disable-sentinel, eager-vs-lazy lifecycle, opt-out mechanism, and
   whether scheduled rebuild is in or out (recommend: out / default-off, own
   follow-up). Then implement #143 backend + CLI flags + docs, then #144
   lifecycle/opt-out. This is the foundation and the biggest immediate win.
1. **ADR-B — server state + control parity surface (#142).** Resolve the
   transport/parity model (which surfaces are MCP-tool + CLI-subcommand vs also
   a direct HTTP route), the HTTP gating mechanism, and the in-flight-registry
   shape. Can be authored in parallel with ADR-A (orthogonal except the
   watcher-state surface).
1. **Implement #142 Tier 1** (status, projects, then watcher-state once step 1
   lands) as MCP tool + CLI subcommand. Small; proves the parity pattern.
1. **Implement #142 Tier 2/3** (logs, then the jobs/queue in-flight registry,
   then `/metrics`). Largest; ship after the pattern is proven.

This sequences highest-value/lowest-cost first (watcher opt-out + tuning),
front-loads the two blocking decisions (parity/transport + gating;
scheduled-rebuild in/out), and defers the only net-new machinery (jobs/queue
registry, `/metrics`) until the pattern is validated.

### 7. Open questions to resolve in the ADR phase

- Transport/parity model: which surfaces are exposed as MCP tool + CLI
  subcommand only (via the `_try_mcp_admin` seam), and which *also* get a direct
  HTTP route — and for those, the gating mechanism (reuse `service_token` as a
  bearer? header vs query param? constant-time compare? loopback-only binding?).
  Note this is parity (CLI gains control through MCP), not a second HTTP control
  transport, so the prior admin-route rejection is honoured.
- `/jobs` (queue/current-activity): scope of the new in-flight registry — does
  it track only watcher-triggered reindexes, or also synchronous tool reindexes
  and search load? What fields (source, phase, started_at, trigger, cooldown
  state)? Build a dedicated registry, or generalise the `ProgressReporter`
  protocol into a serializable server-side state object both the watcher and
  tool paths write to?
- `/metrics`: Prometheus format and exact counter set (search/reindex counts,
  durations, GPU memory) — greenfield.
- `/logs`: tail-N vs full-dump vs SSE stream; reading across rotated files;
  offset/line params; mid-rollover race handling.
- #143 key names, units, and disable-sentinel (`0` = disabled vs `0` = no
  debounce); CLI flag names that avoid collisions.
- #144: eager vs lazy default; per-project vs global watcher/auto-reindex
  config (prior ADRs deferred per-project overrides to "global-only for beta").
- #144 scheduled rebuild: is it exempt from the standing "no background thread"
  constraint, or rejected outright?
