---
tags:
  - '#audit'
  - '#stale-search-hits'
date: '2026-10-26'
modified: '2026-10-26'
body_schema: 'body-v2'
body_hash: 'sha256:fd19e05a339afdff77447afe37c13fccb073a291cb59409b642634074b0560a4'
related:
  - "[[2026-10-26-stale-search-hits-plan]]"
---

# `stale-search-hits` audit: `delivered freshness and explicit repair authority`

## Scope

Integrated review of S01 on branch `feature/stale`, including the working-tree implementation, focused guide, governing decision refinements and final verification. The scope covers final delivered pages for code, vault, documents and combined search; safe bounded file reads; publication fencing; post-response audit scheduling; canonical incremental admission and operator rebuild remediation; CLI/MCP preservation; and runtime shutdown.

Verdict: PASS. No unresolved critical, high, medium or low code findings. The principal agent performed the architecture, source/test implementation and integrated review. Delegated work was limited to read-only context, records/documentation and existing CPU test runs.

## Findings

No unresolved findings. Canonical evidence is captured before retrieval and validated after disk comparison. Unavailable, unsafe, over-budget or racing observations stay unverifiable. A single page shares file bytes across domains and charges attempted reads against its byte budget. Stale hits retain indexed snippets, scores and ordering. Vault stamp-only changes reuse the established semantic fingerprint.

The runtime coordinator owns bounded observations and one audit worker, not publication or job authority. It starts after response delivery, coalesces root/source reports, rechecks continuing drift, and requests only ordinary incremental work through the request runtime's existing JobManager. Exact projection or proven compatibility blockers, and canonical repair-job full-reindex refusals, project executable root/source/port-specific rebuild remediation. Missing/conflicting audit evidence is deferred. Shutdown closes intake and prevents late repair admission. Current verified hits retire their corresponding observation without allowing an old worker completion to overwrite newer state.

## Verification

- 24 new CPU tests pass in `.pytest-tmp/stale-feature-tests.log`: actual file and ledger comparisons, same-size/same-mtime edits, changes beyond shown lines, deletion, vault semantic stamps, document bytes, mixed-domain shared reads, publication races, unsafe/offline roots, final combined service serialization, coalescing, incremental authority, rebuild blockers, job refusal projection, shutdown, post-response scheduling and CLI/MCP round trips.
- 349 existing CPU regressions pass with no skips: 249 search/CLI/MCP/publication cases in `.pytest-tmp/stale-regression.log`, 62 admission/dispatch/rebuild cases in `.pytest-tmp/stale-job-regression.log`, and 38 lifecycle/startup cases in `.pytest-tmp/stale-lifecycle-regression.log`.
- Four mutation sequences failed at their named assertions and passed after restoration: proof fence, incremental-only admission, audit blockers including transient missing proof, and shutdown admission. Evidence is in `.pytest-tmp/stale-mutation-*-fail.log` and matching pass logs. No mutation remains on disk.
- Package Ruff lint, touched-file format checks, ty and strict basedpyright checks pass. Scoped pylint, configured cognitive complexity and guide mdformat checks pass. The initial complexity, module-length and formatting findings were corrected within S01 rather than suppressed.
- GPU inference/end-to-end execution was not run: another process owns the machine GPU. This change adds no inference implementation or model-stack behavior. Existing CPU boundary tests verify the service and adapter paths under isolated state.

## Recommendations

No follow-on decision or implementation revision is required for this scope. Full rebuild execution remains an operator action under the existing lifecycle. Per-hit unverifiable status is an intentional limit of bounded point-in-time checks, and is separate from published-generation readiness.
