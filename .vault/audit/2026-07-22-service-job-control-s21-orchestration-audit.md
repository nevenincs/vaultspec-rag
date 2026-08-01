---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:c8e7b3388b1102e18dd443fa3f0d05548b1f549ed9759c1f4c2bff58ede0d083'
related:
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-research]]"
---

# `service-job-control` audit: `W03.P11.S21 watcher orchestration verification`

## Scope

Reviewed the complete uncommitted S21 change in
`src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py` against
`W03.P11.S21`, the accepted ADR, research, reference, and the S18-S20 audit
outcomes. The review also applied the repository's test-integrity,
managed-singleton isolation, bounded-view, service-domain, GPU, and storage-lock
rules.

The review traced each test through the production `ServiceRegistry`, canonical
`JobManager`, server watcher owner, `watch_and_reindex`, real local `VaultStore`,
real vault and code indexers, real filesystem notifications, and the shared GPU
embedding model. It checked pause coalescing and same-ID reconciliation,
cancellation dirtiness and distinct-ID replacement, replacement backoff,
explicit watcher stop, cleanup joining, runtime and lock release, deterministic
bounds, bounded snapshot observation, and fixture teardown.

## Findings

No findings. The tests import and exercise production behavior directly. They
contain no fake, mock, stub, patch, monkeypatch, skip, or expected-failure path,
and they do not duplicate watcher or job-manager business logic.

The pause scenario holds the real writer lock to establish an observable live
attempt, requests pause through `JobManager`, and waits for exact release before
asserting `paused`. Later filesystem dirtiness remains attached to that one
active job. Resume increments the attempt on the same job ID, records the
reconciliation lineage, indexes both generations, and proves explicit watcher
stop remains pending until the live attempt releases.

The cancellation scenario observes `cancelling` before release, then verifies
the terminal `cancelled` snapshot, cleared runtime and storage ownership, live
watcher intake, the production replacement delay, a distinct replacement ID,
and convergence of both retained and later dirtiness. Snapshot filtering uses
the manager's bounded active-plus-terminal view and adds no alternate operator
state computation.

The async fixture stops every watcher, joins cleanup owners, cancels and joins
any remaining manager attempt, requires an empty active registry, closes every
real project slot, and resets manager and limiter singletons. Session-wide
managed paths remain isolated by the existing autouse fixture, while all local
stores live beneath each test's temporary root. No watcher task, drain, project
lease, writer lock, manager runtime, store, or limiter owner survived the full
file run.

## Recommendations

Approve `W03.P11.S21` for closure. The later S22 and end-to-end steps should
retain this real-component, state-driven synchronization pattern.

Independent verification is green:

- The two new watcher-control cases pass together: 2 passed, 5 deselected.
- The complete integration file passes 7/7 with no skip or expected failure.
- Ruff reports no issue.
- BasedPyright reports 0 errors and 0 warnings.
- `git diff --check` passes.
- A direct prohibited-pattern search returns no match.

The code-review workflow requested an additional reviewer, but the agent thread
limit was already occupied. The primary review therefore performed both the
behavioral trace and test-integrity pass independently.

Final disposition: `CRITICAL 0`, `HIGH 0`, `MEDIUM 0`, `LOW 0`. Approved for
`W03.P11.S21` closure.

## Post-approval decomposition review

The test-only complexity decomposition preserves the approved behavior. The new
helpers group existing observation predicates, intake-disabled assertions,
resource-release assertions, and the cancellation sequence. They call the same
production manager, watcher, registry, filesystem, store, and lock surfaces.
They neither reproduce transition or replacement policy nor compute an alternate
job state.

The delta adds no fake, mock, stub, patch, monkeypatch, skip, or expected-failure
path. Independent verification passes the complete target file 7/7, Ruff,
BasedPyright with 0 errors and 0 warnings, `git diff --check`, the cognitive
complexity check, and scoped Xenon with maximum absolute C, module C, and average
A thresholds.

Delta disposition: `CRITICAL 0`, `HIGH 0`, `MEDIUM 0`, `LOW 0`. Approval remains
unchanged.
