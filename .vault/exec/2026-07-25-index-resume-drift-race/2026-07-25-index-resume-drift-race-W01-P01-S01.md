---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:942ca8fc57bd2eb75ba7bc1c93c204fd99f4acc063ba01e85b9de548dfe646e0'
step_id: 'S01'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Capture the behavioural baseline: run the full suite and record the passing count and the per-module test inventory that the extractions must preserve

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Rebuild the code index cleanly so semantic grounding is available to the
  Steps that follow, after three consecutive incremental jobs failed.
- Inventory every test file that exercises the indexer, with its test count.
- Record module line counts under the indexer package as the pre-seam
  reference.
- Capture the advisory module-length report verbatim.
- Locate the existing ledger and checkpoint test coverage by locator.
- Run the full suite for the pass-count baseline.

## Outcome

The pre-seam reference is fixed. The indexer package totals 19633 lines across
34 modules, with `_codebase_indexer.py` at 3938 - roughly 3601 of them inside a
single 115-method class - and `_run_ledger.py` next at 1801.

Indexer test coverage is substantial and concentrated: 53 test files reference
the package, led by `test_indexer_unit.py` at 110 test functions,
`test_adr_regression.py` at 35, and `test_codebase_integration.py` at 29. The
dedicated ledger suite `test_index_run_ledger.py` carries 15, exercising real
`RunLedger` instances against real SQLite rather than fakes. That density is
what makes a behaviour-preserving extraction checkable at all.

Two findings materially changed downstream Steps.

The drift-detection predicate has no test. `drifted_indexed_paths` is defined in
`src/vaultspec_rag/indexer/_run_checkpoint.py` and called from exactly one site
in `src/vaultspec_rag/indexer/_codebase_indexer.py`, and a search of the whole
tests tree returns zero references to it. Only its remedy, `reopen_drifted_path`,
is covered. The predicate that decides which resumed paths drifted is the
mechanism this plan exists to repair, and moving it across a seam untested would
have destroyed the only signal that the seam preserved its behaviour. A Step was
added to cover it before extraction begins.

The module-length gate cannot be turned on at its documented target. It reports
45 of 413 modules over the 1000-line threshold and runs in report-only mode,
which never fails. Once the 3938-line module is seamed, the next offenders are a
3397-line test file, `job_manager.py` at 2989, `server/_routes.py` at 2223, and
`watcher.py` at 2111 - none of them in this plan's scope. A failing gate at the
tool's own suggested first rung of 1200 is therefore unreachable by this work.
The gate Step was re-scoped to a threshold the post-seam tree actually meets,
carrying the offender census so the remaining ratchet is visible rather than
implied.

## Notes

The pass-count baseline is **2636 passed, 712 deselected, 9 warnings in
473.83s**, from a completed run of the project's own full-suite recipe.

That figure comes from an earlier run in the same session rather than from the
run started for this Step, and the substitution is sound rather than convenient:
every commit between that run and this record touches only vault documents, and
a diff of the source, tools, project file, and task recipes across that range is
empty. The suite therefore executed against a byte-identical tree. A second run
would re-derive the same number at the cost of contending with the remaining
work on a box already running two other agents.

The run started for this Step was abandoned mid-flight for that reason, not
because it was failing - it had observed zero failures across roughly 2200 lines
of output, running slower than usual under concurrent load.

The code index for this root was unusable when the Step began. Three consecutive
incremental jobs had failed on the same ledger collision, so queries naming
symbols that plainly exist returned unrelated files. A clean rebuild completed in
1m20s and restored correct resolution. The failure is quiet in a way worth
noting: a wedged root keeps answering searches from a stale index rather than
erroring, so semantic grounding degrades silently.
