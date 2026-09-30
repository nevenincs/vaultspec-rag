---
tags:
  - '#plan'
  - '#monitor-refinement'
date: '2026-09-30'
tier: L1
related:
  - '[[2026-07-27-jobs-tui-adr]]'
  - '[[2026-07-29-server-watch-observability-adr]]'
  - '[[2026-06-11-service-jobs-operability-adr]]'
  - '[[2026-07-21-managed-log-contract-adr]]'
  - '[[2026-09-21-typesafe-classifier-adr]]'
  - '[[2026-09-30-monitor-tooling-adr]]'
  - '[[2026-09-30-monitor-refinement-reference]]'
modified: '2026-09-30'
body_schema: body-v2
body_hash: 'sha256:904df549f79ff6ffd57175ebea99fee13822323d321d674e3b96e828cf30c44e'
---

# `monitor-refinement` plan

## Description

Approved 2026-09-30

Authorization: the user's feature request authorizes verifying and improving the TUI monitor, separating health, work lifecycle, indexing, serving and actual-work logs, and adding TypeSafe monitoring before the Carbon port. This plan implements wave 1. Carbon work begins only after the integrated review passes.

Decision coverage: unchanged reuse of jobs-tui and server-watch-observability for one responsive owner and service-domain state; service-jobs-operability for lifecycle and initiators; managed-log-contract for bounded grouped sources; typesafe-classifier for daemon enrollment and existing redacted request diagnostics. Monitor-tooling governs the later frontend home. These refinements introduce no endpoint, inference behavior, retention boundary or persisted schema.

The reference 2026-09-30-monitor-refinement-reference records the gaps. Four distinct operator surfaces: daemon health and TypeSafe evidence at the top; indexing work with lifecycle counts; serving with queued/active/recent terminal requests; focused job/request logs and separate raw service/Qdrant review. Job degradation does not substitute for daemon health. Counts name their actual scope. Missing measurements remain unreported. Each domain reports its own freshness/error evidence.

Wave 2 will port the reviewed operator model to Carbon under src/monitor using the Carbon design skill and connected Carbon MCP. Browser authentication and transport need decision assessment then.

## Steps

- [x] `S01` - Separate daemon health from indexing condition, expose TypeSafe evidence and diagnostic units, include queued searches and honest lifecycle counts, and verify rendered behavior; `src/vaultspec_rag/cli/_jobs_tui{,_header,_status,_payload,_state,_cells}.py and focused tests under src/vaultspec_rag/tests`.
- [x] `S02` - Continuously refresh focused logs by job/request identity with bounds, ordering and freshness, verify navigation and controls, keep health failures visible, and record integrated review; `src/vaultspec_rag/cli/_jobs_tui{,_logs,_log,_payload,_state,_status}.py, focused tests under src/vaultspec_rag/tests and monitor-refinement audit`.

## Parallelization

Execute sequentially in this worktree. One agent owns code, vault mutations, gates and commits. S02 depends on S01. No parallel agent assignments.

## Verification

Run package Ruff lint, changed-file Ruff format, ty and strict basedpyright, and accelerator-free covering tests. Use production ledgers/files, real concurrency and Textual pilot rendering; add no mocks or provider calls. Verify queued searches, active/recent identity, separate work counts and daemon health, daemon TypeSafe states and diagnostic units, log updates without reselection, request/job log attribution, late-response ordering, raw source identity and truncation. Exercise wide/narrow key navigation and job-control regressions. Check vault and plan conformance. Do not start the resident service, initialize compute or run GPU/live tests. Close Steps with passing evidence and record an integrated review. Wave 2 readiness requires PASS with all criteria covered.
