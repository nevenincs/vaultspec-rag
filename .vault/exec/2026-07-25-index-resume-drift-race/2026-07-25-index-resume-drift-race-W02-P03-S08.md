---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:b550944b63cce3b9bcae11c8359161384dd11c8c32a3dd0bde6744b4319f76c9'
step_id: 'S08'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Add the cheap pre-record drift re-check that keeps the common case off the signal path entirely

## Scope

- `src/vaultspec_rag/indexer/_run_checkpoint.py`

## Description

- Add the pre-record drift check by widening the existing drift predicate to
  the digests of units about to be recorded, rather than writing a second one.
- State in the predicate's docstring that it answers the pre-dispatch and the
  pre-record question with the same comparison.
- Route the check through the drift owner so the cheap path and the refused
  write share one remedy and one budget.

## Outcome

The check exists and the common case never reaches the exception path, but it
arrived as a reuse rather than as new code, which was the honest outcome once
the two questions turned out to be the same one.

The existing predicate asks which indexed paths carry a digest differing from
the one supplied. Supplying what a scan just observed answers "what moved
while the interrupted attempt was down". Supplying the digests of the units
about to be recorded answers "what moved since dispatch". A separate
pre-record predicate would have been a second copy of one comparison, and the
two would have drifted apart the first time either was changed.

The check runs once per store mutation over that mutation's own paths, so its
cost is bounded by slice size rather than by tree size, and a run with no
drift pays one indexed-state lookup per mutation and nothing else.

One thing this check cannot do is replace the ledger's refusal. A path can
still move between the check and the insert. That window is now measured in
the width of one transaction rather than most of a run, and the refusal
handles it.

Gates: lint clean, format clean, type check reports no diagnostics, and the
checkpoint and ledger suites pass at 30 tests.

## Notes

The step's scope named the checkpoint module and anticipated new code there.
What landed there is a docstring stating the predicate serves both callers;
the routing lives with the drift owner because the budget has to apply to
whichever route catches the path.
