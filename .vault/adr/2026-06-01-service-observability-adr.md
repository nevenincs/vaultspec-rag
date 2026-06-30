---
tags:
  - '#adr'
  - '#service-observability'
date: '2026-06-01'
modified: '2026-06-30'
related:
  - "[[2026-06-01-service-observability-research]]"
  - "[[2026-06-01-service-operability-adr]]"
  - "[[2026-05-31-server-mcp-route-adr]]"
  - "[[2026-05-31-service-token-identity-adr]]"
  - "[[2026-04-12-store-eviction-log-rotation-adr]]"
  - "[[2026-04-12-index-progress-bars-adr]]"
  - "[[2026-05-30-cli-json-output-adr]]"
---

# `service-observability` adr: server state surface — read-only HTTP + CLI/MCP parity (#142) | (**status:** `accepted`)

## Problem Statement

The resident RAG service exposes only `/health` and `/mcp`. In production — a
single resident service shared by concurrent agents against one worktree —
operators and agents that hold only the port cannot see what the service is
doing: what it is indexing, whether the watcher is live, what the log says, or
basic metrics. ADR-A delivered the watcher *control* half of the cluster
(#143/#144/#145); this ADR (issue #142) delivers the *observe/read* half — the
server state surface — under the same governing decision: full CLI ⇄ MCP parity
over the server-runtime surface. It is a read-only monitoring surface plus
MCP-transported reads, **not** a second control plane.

## Considerations

- **Parity, honouring the prior admin-route rejection.** Control rides MCP via
  the existing `_try_mcp_admin` seam (now in the `cli/` package); this ADR adds
  read tools + matching CLI subcommands, and HTTP routes only where MCP's
  structured-tool protocol serves poorly (raw log text, Prometheus metrics).
  That keeps the store-eviction admin-route rejection intact (no duplicate
  control transport).
- **Tiered by cost:** Tier 1 structured reads that mirror existing state; Tier
  2a logs; Tier 2b a net-new in-flight registry for jobs/queue; Tier 3
  `/metrics`.
- **No server-side job state exists today** — reindex tools run synchronously
  with `NullProgressReporter`, and the watcher reindexes invisibly. A jobs/queue
  view requires introducing a lightweight in-flight activity registry.
- **Routing + gating constraints** are settled by prior ADRs (Starlette `Route`
  on the inner app; `service_token` is identity-only, so HTTP gating is a fresh
  decision; `/health` stays ungated).
- **Modular post-split structure:** MCP tools live in the `mcp_server/` package
  (`_state` owns `mcp` + globals); CLI subcommands in the `cli/` package
  (`_service_*` submodules + `_try_mcp_admin`).

## Constraints

- **No second control transport.** New HTTP routes are read-only; all control
  stays on MCP. New routes are registered as Starlette `Route`s on the inner app
  assembled in the `mcp_server/` package (per `server-mcp-route`), never as
  additional ASGI wrappers.
- **HTTP gating decision required.** `service_token` is identity-only today
  (`service-token-identity`). Decision: gate the new read routes by binding the
  HTTP service to loopback only (the daemon already serves on 127.0.0.1) and
  accepting the `service_token` as an optional bearer (`Authorization: Bearer <token>` or `?token=`) compared in constant time; `/logs` and `/metrics`
  require the token, `/health` stays ungated. This is a pragmatic monitoring
  gate, not an auth boundary — documented as such.
- **No background thread.** `/metrics` and jobs state are computed on-demand /
  updated inline by the request and watcher paths — no standing timer thread
  (honours the repeatedly-rejected background-sweeper stance).
- **Log rotation.** A `/logs` reader must span the rotated set (`service.log`,
  `.log.1`, …) and tolerate mid-rollover races.
- **Stable parents.** Builds only on shipped surfaces (the Starlette app, the
  rotating log handler, the registry, the `_try_mcp_admin` seam, the JSON
  envelope + exit-code contract). No new dependency; `prometheus_client` is
  avoided in favour of emitting the text format directly (no new dep, no
  background collector).

## Implementation

Layered by tier; each capability is reachable from both CLI and MCP.

- **Tier 1 — structured state (MCP tool + CLI subcommand).** A consolidated
  `get_service_state` MCP tool returning index counts per source, GPU/device,
  project slots, and a watcher rollup (reusing `get_watcher_state` and
  `list_projects` data). Surfaced via `server service info` (or extend
  `server service status`). No new HTTP route — `service status` already does
  the lifecycle signals over the status file.
- **Tier 2a — logs.** A `get_logs(lines)` MCP tool + `server service logs [--lines N]` CLI subcommand (over `_try_mcp_admin`), PLUS a read-only HTTP
  `GET /logs?lines=N` returning text/plain, gated by the token. A shared log
  reader walks the rotated set newest-last and tolerates a file vanishing
  mid-rollover.
- **Tier 2b — jobs/queue (net-new).** A small thread-safe in-flight registry
  (a bounded list under a `threading.Lock`, living in the `mcp_server/` package
  state) recording each index/reindex activity: `id`, `source`
  (vault/code), `trigger` (tool/watcher), `phase`, `started_at`, optional
  `finished_at`/`result`. The reindex tool paths and the watcher reindex calls
  write start/finish entries (the only behavioural change to existing paths).
  Exposed via `get_jobs` MCP tool + `server service jobs` CLI + optional
  `GET /jobs` JSON HTTP route. Bounded ring buffer (recent N) so it cannot grow
  unbounded; no background reaper.
- **Tier 3 — metrics.** A read-only `GET /metrics` HTTP route emitting Prometheus
  text format directly (counters/gauges held in package state, incremented
  inline by search/reindex paths; GPU memory read on-demand via torch). No new
  dependency, no collector thread.
- **HTTP routes** register in the `mcp_server/` package where the Starlette app
  is assembled (alongside `Mount("/mcp")` + `Route("/health")`), guarded by a
  small token-check helper. **CLI subcommands** extend the `cli/` service group;
  **MCP tools** join the `mcp_server/` admin/observability submodule.

## Rationale

The research showed most of this is exposure of state the service already holds
(status, projects, watcher, logs), so the bulk is parity plumbing, not new
machinery — except the jobs registry, which is genuinely new because no
server-side progress state exists. Computing metrics and jobs inline (no
background thread) respects the standing rejection of background sweepers.
Reusing the identity `service_token` as a loopback-only bearer is a pragmatic
monitoring gate that matches the token's real threat model without inventing an
auth system. Keeping control on MCP preserves the prior admin-route decision
while still giving the CLI full reach.

## Consequences

- **Gains.** Operators/agents can see index state, watcher state, the log,
  in-flight jobs, and metrics from either the CLI or MCP, and scrape `/metrics`
  externally — closing the production blind spot #142 reported.
- **Honest difficulties.** The jobs registry adds a small write on the
  reindex/watcher hot paths (cheap, lock-guarded) and is the one net-new state
  to test carefully (concurrency, bounded growth, multi-project). The `/logs`
  reader must handle rotation races. Token-as-bearer is monitoring-grade, not
  auth — must be documented so no one over-trusts it.
- **Pitfalls.** Metrics/jobs must stay pull/inline (no timer thread). HTTP
  routes must remain strictly read-only. Parity discipline: every new read must
  land on both CLI and MCP.
- **Pathways.** A future remote/containerised service already has the read
  surface it needs; `/metrics` enables fleet dashboards.

## Codification candidates

- **Rule slug:** `service-http-routes-read-only`.
  **Rule:** New HTTP routes on the resident service must be read-only and
  registered as Starlette routes on the inner app; all control flows through MCP
  (and the CLI-as-MCP-client seam), never a second HTTP control transport.
