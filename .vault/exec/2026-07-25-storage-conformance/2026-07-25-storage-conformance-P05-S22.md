---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S22'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Review the delivered feature against the authorizing decision and record the audit

## Scope

- `src/vaultspec_rag/`

## Description

Locate each of the authorizing decision's eight implementation clauses in the
tree, check each plan verification criterion against what shipped, re-run the gate
set, and record the audit.

## Outcome

Seven of the eight implementation clauses are implemented where the decision put
them, each read rather than inferred: the stamp inside the create, verification on
the ensure seam behind the once-per-collection marker, three verdicts with absent
evidence reported as unknown, geometry refusing while model identity degrades, the
manifest preserve, the copy carry, and the degraded reason paired with its rebuild
command.

Four findings carry weight. The survey payload reports the stamped dense model
where the decision asks for the per-collection verdict and the whole stamped
identity - the one verification criterion not met, and not patchable in place,
because a verdict needs a live geometry read the decision confines to the ensure
cache. The complexity gate had been failing since this feature's first
implementation commit and the earlier closeout recorded gates clean by enumerating
a subset that omitted it. A plan criterion asks for reclamation behaviour the
decision does not authorise and that would leak disk without bound if honoured.
And a nonconforming collection's readability is proven by a successful open rather
than by a search returning results.

The audit names the decision a follow-on record must make for the survey gap:
which component owns the join between a per-store-instance verdict cache and a
manifest-derived survey, and what a survey should report for a namespace no store
instance in this process has ever ensured.

## Notes

The review deliberately did not close the survey gap. Closing it means either a
second live geometry read on a path the decision kept free of one, or a new seam
between the daemon's verdict cache and the survey - an architectural choice, not a
patch, and outside the scope this decision commits to.
