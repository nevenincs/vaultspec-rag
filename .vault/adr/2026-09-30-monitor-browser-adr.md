---
tags:
  - '#adr'
  - '#monitor-browser'
date: '2026-09-30'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:13ed1eee5e6f1777cb541dee09d7b5118bb4aa517f114635c4b291692085395b'
related:
  - "[[2026-09-30-monitor-tooling-adr]]"
  - "[[2026-09-30-monitor-refinement-audit]]"
  - "[[2026-09-30-monitor-refinement-reference]]"
  - "[[2026-07-29-server-watch-observability-adr]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-07-21-managed-log-contract-adr]]"
  - "[[2026-09-21-typesafe-classifier-adr]]"
---

# `monitor-browser` adr: `Credential-free local Carbon operator monitor` | (**status:** `accepted`)

## Problem Statement

The reviewed TUI operator model needs the requested Carbon browser implementation. The frontend needs automatic access to the local service without asking for credentials or adding an admin role.

## Considerations

The user explicitly authorizes wave 2 after a robust TUI, chooses a local operator interface, and says no credential or admin gates. The integrated TUI review in 2026-09-30-monitor-refinement-audit passes with 162 covering tests. The frontend home, React/Vite/TypeScript and shared lifecycle are accepted in 2026-09-30-monitor-tooling-adr.

The daemon already publishes its current port/token in the managed service.json discovery document; its existing HTTP routes own authenticated lifecycle and bounded monitoring semantics: `src/vaultspec_rag/config/_paths.py:26`, `src/vaultspec_rag/serviceclient/_discovery.py:389`, `src/vaultspec_rag/server/_routes.py:545`, `src/vaultspec_rag/serviceclient/_transport.py:1163`. Carbon MCP verified the React shell, grid, tables, tabs, tiles, notifications and status indicators. Official package metadata confirms @carbon/react 1.117.0 supports the pinned React 19.3 and Sass 1.105.1 supplies its official styles. Hosted ADR placement is unconfigured; local accepted-decision discovery applies.

## Considered options

- A same-origin loopback Vite/preview adapter over existing service routes is chosen. It uses local discovery automatically and keeps domain behavior with the daemon.
- A browser credential form and persistent token storage are rejected: the user explicitly requests neither, and the daemon's local discovery already resolves credentials for operator clients.
- A new daemon monitoring API or public dashboard is rejected for this scope: existing endpoints suffice. The earlier Tailscale reachability correction is historical; the authorized security correction in `2026-10-04-monitor-access-adr` now confines this credential-free interface to loopback.
- Recreating Carbon controls/styles is rejected in favor of official React components, tokens and compiled component SCSS.

## Constraints

Authorization: the user's wave-2 request and explicit local/no-credentials/no-admin-gates direction authorize this ruling and implementation. The TUI remains the canonical terminal owner; the browser is a presentation adapter, not a second service-domain implementation.

2026-10-01 authorized correction: the user explicitly requires dev/preview binding to 0.0.0.0, access for Tailscale nodes, canonical strict-port start/reattach/recreate behavior, and the devservers CI workflow. That historical network commitment is reversed by the user's 2026-10-04 security-fix request and `2026-10-04-monitor-access-adr`; the current monitor and RAG service are loopback-only.

The frontend and API bridge bind to 127.0.0.1 and require an admitted loopback socket peer, a loopback or .localhost authority and matching Origin when present, for every request. Tailnet peers, Tailnet authorities and identity headers confer no authority. The shared devservers repository continues to own local reverse-proxy aliases. Direct remote mode and Tailscale Serve exposure are unsupported; authenticated tunnels may terminate at loopback. The bridge only targets the port in managed service discovery or an explicit local port override, never an arbitrary upstream URL. It reads the daemon credential internally, refreshes it through existing health recovery when necessary, and never returns it to browser code. The UI has no login, credential prompt, persisted token, or admin role. Restrict forwarding to declared monitor reads and exact service/job controls; forward service capability/revision semantics rather than inventing control authority. The authorized operations expansion below adds canonical service lifecycle and repository enrollment; inference and index-recovery remain separate explicit actions.

Preserve service-owned bounded jobs, queued/active/recent requests, correct diagnostic units, scoped job/request logs, and distinct raw service/Qdrant groups with visible freshness, failures and truncation. Poll independently with cancellation and stale-response protection; retain prior evidence on transport failures. Missing measurements are unreported. No all-time archive or persistent query/result storage is introduced.

Use pinned official @carbon/react and Sass, Carbon Grid at all breakpoints, IBM Plex from the package, accessible shell/tabs/tables/status indicators, and Carbon tokens in custom SCSS. This scopes the previous vanilla-CSS preference to custom browser styling compiled with Carbon SCSS; the shared runtime, lockfile, port allocation, lifecycle script and workflows remain governed by monitor-tooling.

2026-10-01 operations expansion authorized explicitly by the user: add service start/stop through the canonical local lifecycle owner, pause/resume through existing service routes, repository path/watch enrollment, resident eviction, storage survey refresh, resource/client read projections and bounded query return evidence. This replaces the earlier scope-only prohibition on service start and new monitoring endpoints; inference/rebuild remains an explicit separate operation. The frontend remains a presentation adapter with automatic internal credentials. Dashboard shows service status/state, system metrics, version, capacity and diagnostics. Index Requests, Queries and Logs are separate pages reached through a Carbon left navigation rail, with relational evidence nested under its parent. Repositories, Storage, Clients and Performance have their own pages. Storage management uses survey refresh and resident eviction; no destructive storage HTTP operation is added. No persistent query/result archive is introduced.

2026-10-04 authorized credential-recovery refinement: loopback-http-security replaces the health-based token recovery described above. The bridge obtains and refreshes its credential only from protected same-user discovery for the addressed port. Browser users retain automatic server-side credentials and the existing monitor network policy.

2026-10-04 authorized caller-authentication correction: `2026-10-04-monitor-capability-adr` reverses credential-free bridge access, because loopback admission cannot tell the owner from another local account. Every bridge call presents the monitor's capability, delivered in the owner's access link and held in that tab's session storage. The UI still has no login form, credential prompt, admin role or storage that outlives the tab, and the daemon credential remains server-side.

## Implementation

Implement one server-side local bridge shared by Vite dev/preview and the packaged monitor server; it forwards bounded service operations and invokes portable canonical owner commands without exposing credentials. Browser code calls relative monitor routes, validates projections and renders health/TypeSafe, indexing, serving and focused/global logs as separate operator surfaces. Existing exact lifecycle controls remain scoped to the selected indexing job.

## Rationale

A local automatic adapter gives the browser the same operator connection as the CLI without exposing credentials or creating a new daemon protocol. Official Carbon components provide accessible interactions and consistent responsive density; the reviewed service model determines what they display.

## Consequences

Standalone npm dev/preview owns the local browser process through the existing harness. The user's 2026-10-02 request authorizes managed server start/stop to own an additional monitor instance under `2026-10-02-monitor-lifecycle-adr`, including dynamic backend-relative allocation and scratch-state discovery. Both entry paths reuse the existing bridge and network/origin policy; stopping the managed instance ends its browser web server. Release delivery supplies this shared adapter in the compiled monitor server with embedded frontend assets under monitor-delivery; static assets alone remain insufficient. A public or multi-user dashboard, persistent retention or alternate transport requires fresh decision assessment. The operations expansion below authorizes bounded service read projections and in-memory returned query evidence. The current network boundary is the scoped exception in `2026-10-04-monitor-access-adr`; local automatic credentials never authorize direct Tailnet access. No resident service, GPU workload or provider call is needed for implementation verification.
