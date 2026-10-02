---
tags:
  - '#plan'
  - '#monitor-lifecycle'
date: '2026-10-02'
tier: L1
related:
  - '[[2026-10-02-monitor-lifecycle-adr]]'
  - '[[2026-09-30-monitor-browser-adr]]'
  - '[[2026-09-30-monitor-tooling-adr]]'
modified: '2026-10-02'
body_schema: body-v2
body_hash: 'sha256:c0619fdf3e0961ed924be5a15134f0699b4b52215a4c2e15149262e434aef1e8'
---

# `monitor-lifecycle` plan

## Description

Approved 2026-10-02

Authorization: the user requested coupled monitor/server start and stop, backend-relative upward port allocation and user-scratch assignment, then explicitly required resources compiled from our sources. CI, compilation and packaging remain owned by the separate delivery session. This plan preserves the remaining lifecycle work because final verification now depends on its compiled artifact.

Decision coverage: accepted `2026-10-02-monitor-lifecycle-adr` governs the supervisor, executable consumer contract, allocation, discovery and shutdown. Accepted monitor-browser governs bridge admission, credentials and canonical service behavior; accepted monitor-tooling continues to govern source development and frontend gates. The separate monitor-delivery design is a producer dependency, not authority to implement its packaging work here.

Prepared working-tree changes already implement the shared port probe, daemon-owned process, incarnation-safe sidecar cleanup, snapshot publication and canonical CLI output. They have not been committed. The source Vite prototype was exercised with real processes and then removed following the clarification. Current compiled-launcher and service checks pass; positive compiled startup, bridge HTTP and parent-death tests remain pending the real executable. Preserve foreign changes and reconcile the consumer flag spelling with the actual producer before closing the Step.

The user's follow-up explicitly authorizes focused user-documentation edits and asks whether status prints the monitor address. S02 completes that bounded documentation work independently while S01 awaits the producer artifact. It documents the current limitation rather than introducing an unrequested status-output change. Monitor-lifecycle governs command coupling and executable requirements in both Steps; monitor-browser/tooling govern the distinction between the managed monitor and source development. The service-mode guide moves to S02's checkpoint; the remaining runtime, discovery and configuration work stays with S01.

## Steps

- [x] `S01` - Finalize and verify the prepared daemon-owned compiled monitor integration against the producer artifact, then checkpoint the cohesive change; `src/vaultspec_rag/monitor_process.py and _ports.py, cli/_process.py, _service_start.py and _service_stop.py, server/_runtime.py, _main.py, _lifecycle.py and _lifespan.py, serviceclient/_discovery.py, config/_types.py and _registry.py, tests/test_monitor_process.py, test_monitor_process_integration.py, test_machine_discovery.py and test_env_registry.py, src/monitor/server/local-service.ts, .env.example, docs/service-discovery.md and configuration.md, lifecycle ADR/reference and authorized monitor-browser/tooling wording`.
- [x] `S02` - Document monitor commands, address discovery, upward port allocation and compiled-runtime requirements in the existing user guides; `README.md, docs/service-mode.md, docs/cli.md and its canonical dev/generate_cli_reference.py notes, focused documentation verification/review, initial accepted lifecycle ADR/reference and authorized monitor-browser/tooling amendments, plan, audit and generated feature index checkpoint`.

## Parallelization

## Parallelization

No delegated workers. S02 can finish independently while S01 awaits the compiled artifact. The delivery session owns compilation, pinning, installation layout, embedded assets and CI. This session owns Python daemon/CLI supervision, assignment state and lifecycle verification. Until S01 closes, delivery should coordinate edits to `monitor_process.py` and the bridge interpreter seam to avoid overwriting the prepared integration.

## Verification

## Verification

For S01, run the real compiled command through `test_monitor_process_integration.py` with its absolute path in `VAULTSPEC_RAG_MONITOR_BINARY`. Require upward allocation after occupied custom-backend neighbors, an actual shell HTTP response, live canonical backend and lifecycle bridge requests, heartbeat repair preserving the assignment, graceful shutdown, forced parent-pipe death and orphan sidecar cleanup. Reconcile failures in the owning workstream; do not substitute source rendering, test doubles or skipped tests for delivered-binary proof.

For S01, run launcher admission and PID-incarnation guards, deliberately break each new guard and restore it in one uninterrupted sequence, and retain both directions in the tests. Run the covering server/CLI/discovery/browser and environment-registry/documentation suites, Python lint, scoped format/type/complexity gates, frontend lint/format/type gates, configured Markdown checks and vault/plan checks. Review the integration as a whole before reporting completion. Do not initialize GPU models or stop the operator's existing service merely to exercise these routes.

For S02, check each documented command/address claim against the prepared start/stop code and existing status renderer. Run the generated CLI reference check, documentation-convention gate, configured Markdown lint and authored-document format checks, and generator lint/format/type checks. Exercise existing CLI start/stop and documentation-convention tests without launching the GPU daemon. Review the README and guides as one operator workflow. Compiled-executable validation stays with S01 and does not gate the factual documentation checkpoint.

After passing each Step's applicable checks, record it through the owning ledger/progress verbs and commit only the explicitly owned paths on `feature/monitor`. The user subsequently explicitly authorized consolidating all monitor work in this existing monitor worktree and PR, pushing feature/monitor, and merging PR #570 into main. This authorization supersedes the earlier no-push/no-merge restriction. Reconcile the delivery producer and existing CI test jobs as part of that integration.
