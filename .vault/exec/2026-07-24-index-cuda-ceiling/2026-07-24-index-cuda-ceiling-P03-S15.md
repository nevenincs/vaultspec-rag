---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S15'
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
     The S15 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The make the ceiling comparison baseline-consistent by subtracting the baseline from the captured peak and from the derived ceiling on the same side and ## Scope

- `src/vaultspec_rag/memory_probe.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# make the ceiling comparison baseline-consistent by subtracting the baseline from the captured peak and from the derived ceiling on the same side

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Make the ceiling comparison baseline-consistent in `MemoryBudget._classify_failure`: the resident baseline is subtracted from the captured peak AND from the ceiling on the same side, with both terms clamped at zero.
- Thread `cuda_baseline_mb` through budget construction at both enforcing sites (`_begin_memory_budget` in the codebase indexer, `_DocumentResourceBudget`/`_begin_resource_budget` in the document indexer) from `resident_cuda_baseline_mb`.
- Name the baseline-relative measure in the failure detail so the operator reads indexing demand against indexing headroom.

## Outcome

A captured peak is absolute (a post-rebase counter starts at the resident models); subtracting the baseline from only one side would double-count the models and covertly tighten the ceiling into a regression. The symmetric subtraction is mathematically equivalent to the absolute comparison in the normal regime, and the reported values describe indexing headroom.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

None.
