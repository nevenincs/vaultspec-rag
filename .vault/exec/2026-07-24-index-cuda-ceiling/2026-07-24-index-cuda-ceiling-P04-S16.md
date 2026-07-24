---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S16'
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
     The S16 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The prove the cross-job contamination guard fails when enforcement reads the process-global counter and passes when it reads the captured peak, recording both directions and ## Scope

- `src/vaultspec_rag/tests/test_job_resilience.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# prove the cross-job contamination guard fails when enforcement reads the process-global counter and passes when it reads the captured peak, recording both directions

## Scope

- `src/vaultspec_rag/tests/test_job_resilience.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Add `test_budget_enforces_captured_job_peak_not_process_global_counter` and `test_forward_peak_capture_routes_to_thread_recorder_and_keeps_maximum` to `src/vaultspec_rag/tests/test_job_resilience.py`.
- Prove both guards can fail, as one uninterrupted break/observe/restore/observe sequence per mutation.

## Outcome

Both directions observed and recorded:

- Contamination guard RED: with `sample`'s enforced peak re-pointed at the process-global reading, the test failed for the intended reason - `JobError: cuda_memory_ceiling: CUDA allocated high-water 9000.0 MiB exceeded the 1000.0 MiB ceiling at code producer queue wait`. Restored: 1 passed.
- Plumbing guard RED: with the recorder dispatch severed inside the capture bracket, the test failed on the intended assertion - `assert 0.0 == 321.5` (captured maximum never reached the budget). Restored: 1 passed.

The guard's live-measurement patch plays a sibling's mid-flight forward; the assertion is deliberately narrow so any re-pointing of the enforced peak at a process-wide counter trips it.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

None.
