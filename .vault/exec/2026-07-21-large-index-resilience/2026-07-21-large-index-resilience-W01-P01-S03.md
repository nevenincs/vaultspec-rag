---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S03'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace large-index-resilience with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S03 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Upgrade memory observation into an enforceable RSS and CUDA budget sampled outside gpu_lock and ## Scope

- `src/vaultspec_rag/memory_probe.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Upgrade memory observation into an enforceable RSS and CUDA budget sampled outside gpu_lock

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Add immutable RSS and CUDA admission ceilings with immutable current and peak snapshots.
- Sample enforcing measurements outside `gpu_lock` without importing heavy model modules.
- Fail closed with typed outcomes when a configured measurement is unavailable or exceeded.
- Latch the first violating observation atomically so concurrent work cannot continue.
- Preserve the legacy optional observation probe and its zero-fallback compatibility.

## Outcome

Index pipelines can now enforce admitted process and device-memory ceilings at explicit safe
checkpoints. Exact-threshold readings remain valid, RSS wins simultaneous classification,
both CUDA allocated and reserved memory are bounded, and every caller observes the same first
terminal failure once the budget trips.

## Notes

Independent review found three High defects in the first revision: admitted ceilings could be
mutated, unavailable enforcing measurements could silently read as zero, and a concurrent
observation could overwrite a violating snapshot and return success. The final revision makes
all enforcement state read-only to ordinary mutation, separates strict samplers from legacy
observers, and classifies and latches the first failure under one lock.

Final review found no unresolved findings at any severity. Direct threshold, unavailable,
legacy, import-light, and live-sampler probes passed; a 32-thread race produced one identical
latched failure for every post-breach caller. Six focused real tests, Ruff, ty, BasedPyright,
and diff checks passed. No model forward was run.
