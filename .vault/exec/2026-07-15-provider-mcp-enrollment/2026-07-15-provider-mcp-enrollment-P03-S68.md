---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
step_id: 'S68'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Close every S67 review finding with strict shared deadlines, race-safe startup publication, and child-incarnation proof

## Scope

- `service environment`
- `HTTP transport`
- `service discovery`
- `startup fixture`
- `managed Qdrant identity and teardown`
- `real Windows and POSIX regressions`
- `focused gates`
- `documentation`
- `and formal review`

## Description

- Restore every environment mutation after partial context-entry failure.
- Enforce one monotonic deadline across HTTP authentication recovery and retry.
- Serialize every service-status writer through one cross-process lock and
  unique atomic replacement.
- Publish daemon and managed-Qdrant identity before model warming, preserving
  authoritative daemon and attached-child identity across parent writes and
  heartbeats.
- Reserve failure-teardown grace inside the shared model-to-readiness startup
  deadline.
- Bind managed-Qdrant cleanup to owner and child process-incarnation witnesses,
  image, loopback listener, pinned version, storage, and readiness.
- Bound Windows process-start, image, listener, termination, and child-reaping
  inspection by the caller's remaining deadline.
- Add real Windows and WSL regressions for every corrected race, timeout,
  identity, and teardown boundary.
- Update the service-discovery contract and record independent review evidence.

## Outcome

All five S67 findings and every later independent-review finding were
implemented with real-behavior regression coverage. Focused Windows evidence
passed for environment restoration, HTTP recovery deadlines, cross-process
status locking, parent/daemon publication races, readiness-expiry teardown,
subsecond termination, and managed-Qdrant identity and orphan handling. Fresh
WSL evidence passed for attached identity through a later heartbeat, restart
publication failure cleanup, complete ordinary-orphan witness rejection, and
forced-stop child-incarnation rejection.

Repository Ruff, BasedPyright, Ty, and diff-integrity checks passed after the
latest focused corrections.

The fourth independent formal review returned three actionable findings: one
real defect (the pre-spawn orphan reap ran witness inspections with no time
bound, able to wedge the daemon in warming under the machine singleton lock)
and two red regressions the integration commit introduced alongside the
hardening (the managed-running classifier happy-path test left stale by the
incarnation-witness tightening, and a re-auth deadline regression that expired
a stage early on a loaded host). All three were corrected: the reap now
threads one whole-operation deadline through every inspection plus the reap
with a named actionable timeout; the classifier test supplies the witness and
gains a sibling pinning the tightening; the deadline test asserts the
no-reset invariant rather than one timing-fragile stage. A fresh independent
re-review confirmed all three findings closed with real-behaviour coverage
and returned PASS, with one LOW informational note (a pathological
split-response probe case, bounded and non-blocking) recorded as a follow-up.
The S68 closure gate is met; the complete platform release campaign remains
assigned to S69 and receives no carried runtime credit from this step.

## Notes

The first formal review found seven defects beyond the original S67 findings;
the second found three additional medium-severity deadline and attached-identity
defects. The third found two high- and three medium-severity gaps in live-owner
proof, late Windows spawn cleanup, pre-yield rollback, reaper witness timing,
and process-creation accounting. Each finding was accepted and corrected before
broader testing.

No pull request, approval, merge, tag, package publication, release, or ambient
installed-service mutation was performed. Failed test-owned processes were
identified and cleaned explicitly; unrelated installed services were left
untouched.
