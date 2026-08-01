---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:31ec296bf2d5cfc488d598ab510cbf8c089f454b6c23122eba14ec13cd24faed'
step_id: 'S21'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Run the full suite, lint, type, and citation gates and reconcile the result against the recorded baseline

## Scope

- `src/vaultspec_rag/`

## Description

Ran the full gate set on a quiet machine, with no concurrent test processes, and
reconciled the result against the baseline recorded at the start of the plan.

The quiet-machine condition was the point of this run, not incidental. An
earlier mid-plan run reported one failure, and it had to be settled rather than
assumed.

## Outcome

```
2663 passed, 712 deselected, 9 warnings in 553.05s (0:09:13)
```

Against a baseline of `2643 passed, 712 deselected`. The plan added twenty
tests, so the floor is met exactly with no test lost.

Gates: ruff check clean across `src`, ruff format clean, `ty check` clean over
the package, basedpyright `0 errors, 0 warnings, 0 notes` on every changed file,
citation gate clean.

**The mid-plan failure is settled as load-induced, not a regression.** An
earlier full run reported one failure in an overlapping-publication atomicity
test belonging to another team's ledger work. Three checks, in increasing
strength: it passed alone, it passed as a whole module, and it passed in this
clean full run. Its file's most recent commit predates this branch, and nothing
in this plan touches the ledger. The earlier run overlapped two or three
concurrent pytest processes from the mutation proofs, which is the load a
timing-sensitive atomicity assertion is least able to tolerate. Recorded rather
than dismissed, because a failure called a flake without evidence is how a real
intermittent defect gets buried.

One unrelated change was also caught and reverted before the merge: a
directory-wide formatter run had reformatted a test file belonging to the
concurrent ledger refactor. It was cosmetic and entirely outside this feature,
and sweeping another session's file into this merge is exactly the failure mode
that makes a merge unreviewable. Format runs are now scoped to changed files.

## Notes

Template evidence: intro_commit=313fdd9ad03fc74d3e0be01c09819d5268deb45a; template_commit=313fdd9ad03fc74d3e0be01c09819d5268deb45a:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
