---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S10'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Run the split classifier over the full corpus on the unscoped escalation so convergence is reached by digest comparison and payload updates rather than a blanket re-embed

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

- Trace the escalation to its execution point: a retry decision requiring an
  unscoped pass resolves the attempt scope to no paths in
  `src/vaultspec_rag/watcher_execution.py:582`, and the vault branch at
  `src/vaultspec_rag/watcher_execution.py:637` hands that straight to
  `incremental_index(changed_paths=None)`.
- Confirm that entry point is the full-scan branch the split classifier now
  governs, so the escalated pass converges by digest comparison and payload
  updates.
- Add two guards over that exact call in
  `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`.

## Outcome

No production change was required, and none was made. The escalation already
routed to the full-scan incremental path; what that path costs changed when the
split classifier landed in P02, and the escalation inherited it.

The guards make the inheritance a fact rather than a reasoned expectation. Over a
corpus where every document was stamp-churned and exactly one body was genuinely
edited, the unscoped pass reports `updated == 1`. Before P02 the same pass
re-embedded all six.

## Notes

The plan's locator for this Step named a watcher module that does not exist under
that path; the escalation lives in the modules cited above. The Step's intent -
narrow what the escalated pass does - was satisfiable without touching either.

Writing a guard was the honest alternative to ticking a Step that needed no code:
a claim that convergence is now cheap is worth exactly as much as the assertion
that can catch it becoming expensive again.
