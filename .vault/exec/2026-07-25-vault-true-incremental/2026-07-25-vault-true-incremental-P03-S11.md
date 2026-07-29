---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S11'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Leave the durable convergence-pending bit and the escalation trigger semantics unchanged, confirming only the work the escalated pass performs is narrowed

## Scope

- `src/vaultspec_rag/watcher_retry.py`

## Description

- Confirm no watcher, retry, durability, or intake module appears in the change
  set for this plan.
- Confirm the durable convergence-pending bit is still persisted by
  `src/vaultspec_rag/watcher_durability.py:316` and still consumed as an intake
  trigger at `src/vaultspec_rag/watcher_intake.py:477`, both untouched.
- Confirm the escalation trigger - the retry attempt set that makes a pass
  unscoped - is untouched in `src/vaultspec_rag/watcher_execution.py`.
- Run the watcher retry and transition-logging suites.
- Add a guard asserting the escalated pass still converges state nobody announced.

## Outcome

The escalation keeps its semantics entirely. It fires on the same condition, is
persisted across restarts by the same durable bit, and still hands the indexer an
unscoped scope. Only what that scope costs changed, which is what the decision
asked for.

The convergence guarantee is asserted rather than assumed: the added guard
deletes one document and creates another behind the indexer's back, then runs the
unscoped pass and requires it to report one added and one removed and to leave
the store agreeing. Narrowing the work must not narrow what the pass reconciles,
and that is the assertion that would catch it if it did.

## Notes

The watcher retry suite passes in full. One test in the transition-logging suite
fails, both before and independently of this change: `JobState.SUPERSEDED` reaches
the failure branch without being classified. It was introduced by the commit that
added that state to the enum, after the test was written, and the test's own
docstring anticipates exactly this case. It touches no code in this plan and was
left alone rather than fixed under an unrelated feature - deciding whether a
superseded job is a failure is a service-surface decision, not a fingerprint one.
