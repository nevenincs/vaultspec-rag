---
tags:
  - '#plan'
  - '#monitor-operations'
date: '2026-10-01'
tier: L1
related:
  - '[[2026-09-30-monitor-browser-adr]]'
  - '[[2026-09-30-monitor-tooling-adr]]'
  - '[[2026-07-29-server-watch-observability-adr]]'
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-07-14-storage-namespace-hygiene-adr]]'
modified: '2026-10-01'
body_schema: body-v2
body_hash: 'sha256:faabda5e409d72502f1718e95239a57bef0c763a0e58fcfd4a6a994dbc85e69e'
---

<!-- RETIRED: S02 -->

# `monitor-operations` plan

## Description

Approved 2026-10-01

The user authorizes service lifecycle controls, header freshness/version, sidebar, separate Dashboard, Index Requests, Queries and Logs pages, relational request evidence, repository enrollment/worktrees/seats, storage management, clients and resource monitoring. Reuse monitor-browser and monitor-tooling with the explicitly authorized operations expansion; preserve canonical service owners and bounded observations. Prior monitor-browser S03 external tailnet rollout remains separate.

User clarifications: Dashboard is the opening service/system overview; Index Requests, Queries and Logs remain separate pages reached from the left navigation rail. Show actual embedding/reranking/sparse model identifiers and TypeSafe API enrollment as configuration, not third-party health. Official Carbon Charts 1.27.20 extends the pinned Carbon dependency family for resource and storage meters. S01 includes offloading and validating resident eviction so management cannot block the service event loop.

## Steps

- [x] `S01` - Implement and verify canonical backend operations for repository enrollment, resident storage management, lifecycle bridge, resource/client monitoring and bounded query evidence; `src/vaultspec_rag service/runtime modules and covering tests, src/monitor/server/local-service.ts and bridge tests`.
- [x] `S03` - Build and verify separate Carbon dashboard and operational pages with relational evidence; `src/monitor frontend components/styles, package.json/package-lock.json and rendered browser checks`.
- [x] `S04` - Verify and review integrated operator workflows and checkpoint results; `monitor covering checks, vault execution and audit records`.
- [x] `S05` - Repair theme switching, collapsible navigation, canonical service-state presentation and responsive mobile workflows; verify rendered interactions and notification colors; `src/monitor shell, controls, styles, tables and lifecycle bridge, package.json/package-lock.json, dev/monitor-browser.mjs, browser and bridge tests`.
- [x] `S06` - Correct disclosure direction and preserve expansion through polling, replace split-pane request envelopes with readable inline details, remove all nested wrapper spacing, support numeric sorting and paginated filtered request/log lists, and keep repository/storage inventory available without the daemon; `src/monitor, canonical service list/log and persisted inventory owners, corresponding backend and rendered tests`.

## Parallelization

S01 backend_inventory owns repository enrollment/storage modules, backend_runtime owns runtime metrics/query evidence and shared Python route registration, and bridge_controls owns the Node local-service bridge and bridge tests. These disjoint backend assignments may execute alongside S03 principal-owned frontend design and coding. Principal serializes shared metadata, integrated checks and commits. S02 was consolidated into S01 because shared route registration makes these backend modules one cohesive runnable checkpoint. S04 follows integration. Backend agents use GPT-6.1 Sol high as requested.

## Verification

Run frontend lint, formatting, strict types and build; backend lint, format, types and focused tests; production-route and installed-browser checks at desktop/mobile. Verify lifecycle state, enrollment/storage operations, missing telemetry, relational request evidence, header freshness and navigation. Preserve bounded responses and redaction; prove negative guards fail then pass. Integrated review and plan checks gate completion.
