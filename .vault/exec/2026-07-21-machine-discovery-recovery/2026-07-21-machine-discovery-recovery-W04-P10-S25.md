---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S25'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Exercise isolated end-to-end start, corruption, heartbeat repair, reconcile, search resolution, and clean shutdown

## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`

## Description

- Extract committed `61ce0d79` into a dedicated clean detached worktree so the run
  reads no uncommitted change from the shared development tree.
- Resolve imports at the extracted source rather than the editable install, and
  confirm the resolution before collecting.
- Run the whole real-process lifecycle suite in that extract, unfiltered, with no
  marker narrowing and no first-failure stop.

## Outcome

The isolated end-to-end lifecycle verification passes: 32 passed, 0 failed, in
12 minutes 32 seconds against committed `61ce0d79` on real processes.

Every behaviour the Step names is covered by a test that ran and passed:

- Start: a daemon starts, answers health, and stops; a second start against a
  live daemon reports already-running rather than racing it; a stale recorded pid
  recovers instead of refusing forever.
- Corruption: a machine pointer missing its pid or its service token is rejected;
  a live legacy status file without a singleton owner is rejected; an attached
  Qdrant without a complete live-incarnation witness is refused across each
  tampered identity field.
- Heartbeat repair: discovery views deleted underneath a live owner self-heal on
  the owner's next heartbeat, and a late heartbeat cannot resurrect state that
  shutdown cleanup already removed.
- Reconcile: reconcile recovers discovery without touching the daemon, holding the
  read-only property the decision record requires of it.
- Search resolution: multi-project search isolation resolves each root to its own
  namespace through the live service.
- Clean shutdown: a running service stops; a stop by port succeeds with no status
  file present; shutdown interrupts only after the worker releases and then
  reopens the store; a race-losing daemon self-exits.

The closing review had already returned PASS while deferring exactly this
execution evidence, having assessed test integrity by reading because the
discovery tests can touch the live machine singleton and the device was in use.
That evidence now exists, so the review's stated condition for closure is met.

## Notes

The run was performed in a clean extract rather than the shared tree, matching the
standard this phase already set for its verifies after an earlier run in a sibling
plan's phase was contaminated by uncommitted work. That precaution proved to be
load-bearing rather than ceremonial: the shared tree currently carries a real red
test in the install and torch-configuration surface, introduced by an unrelated
concurrent refactor. The same test passes in the clean extract. A verification run
taken from the shared tree would therefore have reported a failure this plan does
not own.

Test isolation held under contention. The suite spawns and reaps real daemons and
real managed Qdrant children while a separate resident service and several other
worktrees were live on the same machine, and it neither disturbed them nor was
disturbed by them. No test-owned process was left behind, and no unrelated
installed service was touched.

Two low follow-ups from the closing review remain open by that review's own
recommendation and are not part of this Step: anchoring the contract document's
code citations to symbol names rather than line numbers, and defensively rejecting
an owner-less pointer on the read side. Neither gates closure.
