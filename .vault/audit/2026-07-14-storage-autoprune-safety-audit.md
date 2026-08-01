---
tags:
  - "#audit"
  - "#storage-autoprune-safety"
date: '2026-07-14'
related:
  - "[[2026-07-14-storage-autoprune-safety-adr]]"
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
promoted_to:
  - 'rule:storage-maintenance-is-lifecycle-inert'
  - 'rule:automated-destruction-requires-time-confirmed-danglingness'
modified: '2026-07-14'
body_hash: 'sha256:6b317233eb8ada6eddd62c6ea8a3f6448f48f29ac29de811567db24d979196af'
---

# `storage-autoprune-safety` audit: `execution review of the scheduled auto-prune and attribution`

## Scope

Post-execution review of the eleven-step plan, commits `ba8ad7b` through
`e07446e`: the persisted grace clock, the two-tier reclamation engine with
bounded archives, the config knobs, the in-daemon maintenance loop with
jobs/metrics wiring, the lifecycle-inertness regression guards, the live
integration test, and the shutdown-attribution work. Reviewed with data
safety as the top priority, then event-loop/service safety, lifecycle
inertness, attribution, and test integrity.

## Findings

### data-safety | pass | the reclaim gate stack is non-bypassable and fail-closed

Only survey-classified `orphaned` entries enter `evaluate_reclaim`;
`delete_prefix` independently re-checks the canonical prefix regex and
manifest attribution; a failed archive raises before the drop is reached,
so a point-bearing namespace is never destroyed without its snapshot; and
the grace clock is fail-safe under cross-process manifest races - a lost
or reset stamp can only EXTEND protection, and a clobbered entry demotes a
namespace to `unknown` (never auto-touched), never fabricates `orphaned`.
The archive `os.replace` is provably intra-volume: the supervisor pins
qdrant's snapshots path to the same storage parent the archive dir lives
under.

### service-safety | pass | the tick cannot starve or destabilize the daemon

The cycle runs in a worker thread, holds no store or GPU lock, imports no
torch, closes its client in a finally, and the loop's failure path awaits
a 60-second backoff so a pre-sleep exception can never pin the event loop
(the failure mode the first live run demonstrated). The interval floor is
one second.

### lifecycle-inertness | pass | both regression guards are load-bearing

The fresh-interpreter import-graph test proves the maintenance import
chain pulls in no `vaultspec_rag.cli` module; the source scan catches
function-local imports by helper name. Attribution fields ride exactly
the three terminating stop envelopes and the audit line.

### toctou-empty-drop | low | re-count before the empty-tier drop as defense-in-depth

Between the survey's point count and the drop, a namespace could in
principle gain points (a reindex of a just-restored root racing the
cycle). The 24h continuous-orphan window makes this negligible, but the
empty tier has no archive, so a pre-drop re-count is cheap insurance.
Applied post-review.

### manifest-second-writer | low | document the daemon-side stamp writer

`update_orphan_stamps` adds a second cross-process writer to the
last-writer-wins manifest. The race is delete-safe by construction; a
docstring note keeps the invariant legible. Applied post-review.

### jobs-docstring-taxonomy | low | record_start docstring lags the widened taxonomy

The `source`/`trigger` docstring still names only the reindex values.
Applied post-review.

### initiator-cmd-logging | low | argv logging is a constraint on future stop flags

`initiator_cmd` logs the bounded command line; no stop flag carries a
secret today, and none may be added without revisiting this field.
Documented on the helper. Applied post-review.

## Recommendations

- The four LOW fixes are one-liners; applied in a follow-up commit within
  this execution cycle.
- Promote the ADR's two codification candidates
  (`storage-maintenance-is-lifecycle-inert`,
  `automated-destruction-requires-time-confirmed-danglingness`) after the
  customary full execution cycle.
