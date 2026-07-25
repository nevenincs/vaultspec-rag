---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S01'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace index-resume-drift-race with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S01 and 2026-07-25-index-resume-drift-race-plan placeholders are machine-filled by
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
     The Capture the behavioural baseline: run the full suite and record the passing count and the per-module test inventory that the extractions must preserve and ## Scope

- `src/vaultspec_rag/tests/` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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

The full-suite pass count is not yet recorded. The run was still in progress at
the time of writing, having observed zero failures across roughly 2200 lines of
output, and it is running slower than its usual duration under concurrent load
from another session's suite and the resident GPU service. The count is
deliberately left unrecorded rather than estimated: this number exists to be
compared against after four extractions, and an invented baseline would be worse
than none.

The code index for this root was unusable when the Step began. Three consecutive
incremental jobs had failed on the same ledger collision, so queries naming
symbols that plainly exist returned unrelated files. A clean rebuild completed in
1m20s and restored correct resolution. The failure is quiet in a way worth
noting: a wedged root keeps answering searches from a stale index rather than
erroring, so semantic grounding degrades silently.
