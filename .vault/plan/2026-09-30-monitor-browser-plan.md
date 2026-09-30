---
tags:
  - '#plan'
  - '#monitor-browser'
date: '2026-09-30'
tier: L1
related:
  - '[[2026-09-30-monitor-browser-adr]]'
  - '[[2026-09-30-monitor-tooling-adr]]'
  - '[[2026-09-30-monitor-refinement-audit]]'
  - '[[2026-07-29-server-watch-observability-adr]]'
  - '[[2026-06-11-service-jobs-operability-adr]]'
  - '[[2026-07-21-managed-log-contract-adr]]'
  - '[[2026-09-21-typesafe-classifier-adr]]'
modified: '2026-09-30'
body_schema: body-v2
body_hash: 'sha256:c0960fc26f054811de8fbf5c98230c627eb1bd7fd6d34a5b8ab2f00c0830653f'
---

# `monitor-browser` plan

## Description

Approved 2026-09-30

Authorization: the user requests the Carbon port after the TUI is robust, chooses a local operator interface, and explicitly asks for no credential or admin gates. TUI readiness is PASS in 2026-09-30-monitor-refinement-audit; commits d56f54ef and 39c0365f close wave 1. This plan implements wave 2 under monitor-browser and existing service-domain decisions.

Reuse the root React/Vite/strict-TypeScript harness and shared lifecycle. Pin official Carbon React and Sass, add an automatic server-only local bridge over existing routes, then render separate health/TypeSafe, indexing lifecycle, queued/active/recent serving, scoped logs and source-grouped service logs. Job controls preserve existing capability and revision contracts. Local monitoring has no login or credential entry.

## Steps

- [x] `S01` - Implement and verify an automatic local-only monitoring adapter, pin Carbon dependencies, and reconcile frontend decision wording; `src/monitor/server, vite.config.ts, package.json/package-lock.json, bridge covering checks and enrolled Node runtime in existing test workflows, monitor-browser ADR and monitor-tooling ADR`.
- [ ] `S02` - Implement the responsive Carbon operator UI with independent polling, lifecycle views, TypeSafe details, work/global logs and existing job controls; verify and review the integrated browser monitor; `src/monitor, frontend verification configuration as needed and monitor-browser audit`.

## Parallelization

Execute sequentially in this worktree. One agent owns vault records, source, tests and checks. Browser presentation depends on the bridge. No parallel agent assignments.

## Verification

Run npm lint, format checks, strict TypeScript and build, plus focused production-route/middleware and rendered browser checks at desktop and narrow widths. Verify automatic local discovery, token redaction, bounded reads, failure handling, independent polling, queue/recent counts, TypeSafe details/units, selected-work identity, grouped raw logs and service-owned controls. Use real HTTP routes/files and existing installed browser infrastructure; no mocks, resident daemon, inference, provider calls, GPU tests or semantic recovery. Prove new negative guards fail when broken and pass after restoration. Run Carbon MCP code audit and integrated review, vault and plan checks; close and commit each Step.
