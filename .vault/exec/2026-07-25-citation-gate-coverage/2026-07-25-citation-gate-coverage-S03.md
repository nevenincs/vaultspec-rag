---
tags:
  - '#exec'
  - '#citation-gate-coverage'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:f1f2984b013892776b8f428ca8f6366884daa0f3b3b7a814e42db472006d5ad0'
step_id: 'S03'
related:
  - "[[2026-07-25-citation-gate-coverage-plan]]"
---

# Add guard tests for every shape the gate claims to catch and mutation-prove each direction

## Scope

- `src/vaultspec_rag/tests/test_citation_gate.py`

## Description

- Add ten cases covering the bare dated stem, the reported line inside a module
  docstring, each prose surface in turn, the string-value carve-out, the plain
  date and numeric date range, the tooling surface, and the checkout as a whole.
- Assert the exact slug and the exact matched text rather than a shared failure
  message, so a case cannot pass on whichever pattern happens to fire.
- Break each guard in turn, run its own test alone, restore, and re-run.

## Outcome

Six mutations, each landing red on the assertion it names, in one uninterrupted
sequence with an unconditional restore. Re-narrowing the stem pattern to require
a type suffix reddened six cases including all four prose-surface variants;
reverting the tooling walk to leak-scanning only reddened the tooling case;
skipping the module docstring in the walk reddened the line-number case;
extending the citation scan to string values reddened the data carve-out;
dropping the letter requirement from the stem tail reddened the numeric date
range; and restoring the removed pointer in the profiler reddened the whole-tree
case. With every mutation restored, all ten pass.

That last mutation is the load-bearing one: it is the only direct evidence that
the whole-tree case would notice a real citation rather than simply reporting
the tree it was handed.

## Notes

The scan entry points had to take their roots as parameters before any of this
was possible. A gate that can only be run against the live checkout can be
confirmed green but never shown able to go red, which is the exact failure being
corrected - so the parameterisation is part of the fix, not test scaffolding.

No mutation was left on disk; the restore was verified by re-reading both
mutated files after the sequence.
