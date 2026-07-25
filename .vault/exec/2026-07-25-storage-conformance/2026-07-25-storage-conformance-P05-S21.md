---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S21'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-conformance with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S21 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Run the full suite, lint, type, and citation gates and reconcile the result against the recorded baseline and ## Scope

- `src/vaultspec_rag/` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
