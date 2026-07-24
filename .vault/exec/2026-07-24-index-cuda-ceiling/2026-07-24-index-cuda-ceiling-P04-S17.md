---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S17'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace index-cuda-ceiling with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S17 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The prove the double-count guard fails when the baseline is subtracted from only one side of the ceiling comparison, recording both directions and ## Scope

- `src/vaultspec_rag/tests/test_config.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# prove the double-count guard fails when the baseline is subtracted from only one side of the ceiling comparison, recording both directions

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Add `test_cuda_ceiling_comparison_is_baseline_consistent` to `src/vaultspec_rag/tests/test_config.py`: a peak between (ceiling - baseline) and the ceiling must be admitted; a peak just above the ceiling must be rejected, with the baseline-relative measure named in the detail.
- Prove both single-side mutations fail the guard, as one uninterrupted sequence per mutation.

## Outcome

Both directions observed and recorded:

- Ceiling-only subtraction RED: with the baseline removed from the peak side only, the admitted-path observation (900 MiB, inside the true 1000 MiB ceiling) was wrongly rejected - `cuda_memory_ceiling: ... 900.0 MiB exceeded the 600.0 MiB ceiling` - the exact covert tightening the guard exists to catch. Restored: passed.
- Peak-only subtraction RED: with the baseline removed from the ceiling side only, the over-ceiling observation (1050 MiB) was wrongly admitted - `Failed: DID NOT RAISE JobError`. Restored: passed, full modules 132/132 green.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

None.
