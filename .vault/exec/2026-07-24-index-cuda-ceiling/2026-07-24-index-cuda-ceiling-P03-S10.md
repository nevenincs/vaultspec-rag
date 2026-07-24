---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S10'
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
     The S10 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The add a bare peak reset-and-read helper that resets peak stats without flushing the allocator cache and ## Scope

- `src/vaultspec_rag/memory_probe.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# add a bare peak reset-and-read helper that resets peak stats without flushing the allocator cache

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Add `_reset_cuda_peak_stats_bare` to `src/vaultspec_rag/memory_probe.py`: rebases the allocator peak counters without `empty_cache`, because the per-forward capture bracket runs inside the GPU-lock hold and a cache flush there would add a device synchronisation per encode sub-batch.
- Add `_read_cuda_peak_allocated_mb` as the single sanctioned reader of the process-global peak counter, meaningful only inside the bracket that just rebased it.
- Refresh the `reset_cuda_peak_memory_stats` docstring: the per-run reset is now allocator hygiene at admission; enforcement no longer consumes the process-global counters.

## Outcome

Bare reset and read helpers exist alongside the throttled per-run reset; guarded probes return `False`/`None` off the GPU path so CPU-only hosts degrade silently.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

None.
