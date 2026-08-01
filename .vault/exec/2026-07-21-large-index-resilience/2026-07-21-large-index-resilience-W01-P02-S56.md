---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:d9e1eb29413591fee8f74ff6676c3c3416bcdc360bf2726fc4ea47f7af73d904'
step_id: 'S56'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Stop the retained-point lookup excluding carried-forward evidence, so points inherited from a parent generation are no longer classified obsolete and deleted

## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py`

## Description

- Remove the predicate pinning candidate points to the querying generation,
  and its bound parameter, from the retained-point lookup
  (`src/vaultspec_rag/indexer/_run_ledger.py:1220`).
- Record at the query why the points table is deliberately left unconstrained,
  so the predicate is not reintroduced as an apparent omission.

## Outcome

An ordinary incremental run no longer deletes the inherited half of the index.

The defect had a known-good and known-bad commit either side, established by
bisecting a pristine tree rather than by reading. Extracting each revision with
`git archive` into a scratch directory and running the suite against it with the
interpreter path pointed there isolates committed history completely: no
uncommitted work from any concurrent effort is present, and the shared worktree
is never touched. That is what made the attribution decisive rather than
plausible. The last green revision is the documentation-only commit at 17:53;
the first red one is the finalization-lookup bound at 17:55, and a revision from
the previous evening is green.

That commit rewrote the retained-point lookup to force a join order, and in
doing so introduced a predicate constraining candidate points to the generation
being queried. Carried-forward file states make that predicate wrong. The
carry-forward copies rows under a new generation while preserving the
`evidence_generation_id` that produced them, so the two legitimately differ, and
the join chain ties points to units to that evidence generation - meaning
inherited points belong to the parent. Constraining them to the querying
generation returned none of them. The caller reads an absent point as no longer
retained, classifies it obsolete, and deletes it.

The predicate was redundant for correctness before it was wrong: the joins
already pin points to whichever generation owns the matching unit. Removing it
restores the original semantics exactly, and the two count-shaped integration
failures clear.

This was visible in production and had been misread as consolidation from the
day's refactoring. The live service reported roughly 4,900 code chunks against
about 8,850 measured earlier the same session - close to half the index removed
by routine incremental runs, silently, with no error surfaced anywhere. The
failing assertions were the edge of that, not the whole of it: a count that
fails to rise after a file is added, and a count that falls from three to two,
are both what deletion of inherited points looks like from outside.

The accompanying scan-bounding measurement and the regression guard are separate
Steps, because removing this predicate alone would have traded the data loss for
an unbounded scan, and because nothing in the suite asserted that inherited
points survive at all.

The file carries two queries constraining candidate points to a generation, and
only one is defective. The second was examined rather than pattern-matched, and
it must keep its predicate.

The defective site joins through file states. It asks which of a bounded set of
points is still retained, and reaching that answer requires the file state that
vouches for them - which is where the inherited evidence generation enters and
where constraining points to the querying generation goes wrong.

The legitimate site enumerates a generation's own committed points. It joins
points to units and stops there: no file-state join, no evidence generation
anywhere in it. Carry-forward cannot reach it, because carry-forward copies file
states only - its insert reads from and writes to that one table and never
touches commit units. So a generation's units, and therefore its points, are
genuinely its own, and the predicate expresses exactly that.

Both halves were established by running a real ledger rather than by reading.
A published generation was carried forward into an inheriting one, and the
inherited path's state is confirmed present in the child. Enumerating the child
returns only the child's own point; enumerating the parent returns only the
parent's. The same query with the predicate removed returns both, leaking the
parent's points into the child's enumeration - and the callers of that
enumeration compute which identities a run newly introduced, in order to roll
them back. Removing it there would make a failed run delete points it never
created, which is the same class of harm as the defect being repaired, pointed
the other way.

So one predicate was removed and one was deliberately kept, for opposite reasons
that both reduce to the same rule: points belong to whichever generation
committed them, and a query should constrain them only when it means to ask
about that generation's own work.

## Notes

The separate rollback regression - a point surviving a failed attempt that
should have been rolled back - is NOT cleared by this change and remains open.
It was introduced elsewhere: the test covering it was added and passing at 04:57
and is failing by 15:52, a window that does not contain the commit repaired
here. It needs its own bisect and its own Step.

The fix was applied to another effort's committed work, on assignment, after
having deliberately not applied it when the defect was first found. The
original commit existed to bound a scan, and that intent was measured rather
than assumed before this landed.

The suite around this change is green - twenty-nine ledger, migration, and
checkpoint tests, and two hundred and thirty-nine unit tests in the surrounding
area - but the whole integration suite is not, and will not be until the
rollback regression is addressed. Verification of this Step is therefore the
specific tests named here, never a green suite.
