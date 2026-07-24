---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S14'
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
     The S14 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The enforce every sample checkpoint against the captured baseline-net peak so no path reads max_memory_allocated directly and ## Scope

- `src/vaultspec_rag/memory_probe.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# enforce every sample checkpoint against the captured baseline-net peak so no path reads max_memory_allocated directly

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Re-plumb `MemoryBudget.sample` in `src/vaultspec_rag/memory_probe.py`: the enforced CUDA peak is now the job's captured forward maximum; the live allocated/reserved readings stay on the snapshot as process-global diagnostics only.
- Delete the process-global high-water measurement helper so no enforcement path can read `torch.cuda.max_memory_allocated` directly; the capture bracket is the single sanctioned reader.

## Outcome

Non-forward checkpoints - including the field-failing producer/consumer queue-wait labels - enforce against the job's own captured peak. `sample` keeps its outside-the-lock contract; the number is fed out of the critical section, the sampling never moves into it.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

None.
