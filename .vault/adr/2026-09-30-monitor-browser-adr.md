---
tags:
  - '#adr'
  - '#monitor-browser'
date: '2026-09-30'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:dc8102dd26e7c66b590e526896b4ec28f420018b0de4adf620a15229db0480ec'
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
- A new daemon monitoring API or public dashboard is rejected for this scope: existing endpoints suffice. The 2026-10-01 user correction requires the workstation operator interface to be reachable by Tailscale nodes through the shared devservers configuration.
- Recreating Carbon controls/styles is rejected in favor of official React components, tokens and compiled component SCSS.

## Constraints

Authorization: the user's wave-2 request and explicit local/no-credentials/no-admin-gates direction authorize this ruling and implementation. The TUI remains the canonical terminal owner; the browser is a presentation adapter, not a second service-domain implementation.

2026-10-01 authorized correction: the user explicitly requires dev/preview binding to 0.0.0.0, access for Tailscale nodes, canonical strict-port start/reattach/recreate behavior, and the devservers CI workflow. The earlier loopback-only browser assumption was too narrow; the RAG service itself remains a local machine service.

The frontend and its API bridge bind to the manifest's 0.0.0.0 host and accept matching-origin local or Tailscale clients at declared hosts or Tailscale addresses. The devservers repository owns local reverse-proxy aliases and private tailnet HTTPS mappings. Tailscale's IPv4 100.64.0.0/10 and IPv6 fd7a:115c:a1e0::/48 client ranges are recognized; forwarded headers do not expand client authority. The bridge only targets the port in managed service discovery or an explicit local port override, never an arbitrary upstream URL. It reads the daemon credential internally, refreshes it through existing health recovery when necessary, and never returns it to browser code. The UI has no login, credential prompt, persisted token, or admin role. Restrict forwarding to monitor reads and exact job controls; forward service capability/revision semantics rather than inventing control authority. No service-start, inference or index-recovery action is added.

Preserve service-owned bounded jobs, queued/active/recent requests, correct diagnostic units, scoped job/request logs, and distinct raw service/Qdrant groups with visible freshness, failures and truncation. Poll independently with cancellation and stale-response protection; retain prior evidence on transport failures. Missing measurements are unreported. No all-time archive or persistent query/result storage is introduced.

Use pinned official @carbon/react and Sass, Carbon Grid at all breakpoints, IBM Plex from the package, accessible shell/tabs/tables/status indicators, and Carbon tokens in custom SCSS. This scopes the previous vanilla-CSS preference to custom browser styling compiled with Carbon SCSS; the shared runtime, lockfile, port allocation, lifecycle script and workflows remain governed by monitor-tooling.

## Implementation

Implement a small server-only Vite middleware in src/monitor/server, shared by dev and preview. It performs bounded local HTTP forwarding with no-store responses. Browser code calls relative monitor routes, validates projections and renders health/TypeSafe, indexing, serving and focused/global logs as separate operator surfaces. Existing exact lifecycle controls remain scoped to the selected indexing job.

## Rationale

A local automatic adapter gives the browser the same operator connection as the CLI without exposing credentials or creating a new daemon protocol. Official Carbon components provide accessible interactions and consistent responsive density; the reviewed service model determines what they display.

## Consequences

npm dev/preview owns the local browser process through the existing harness. A built static bundle needs that local adapter to read the service. A public or multi-user dashboard, changed retention, new service endpoint or alternate transport requires fresh decision assessment. Tailnet Serve enablement is an external Tailscale prerequisite; the client never invents a successful proxy mapping when that prerequisite is absent. No resident service, GPU workload or provider call is needed for implementation verification.
