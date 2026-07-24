---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S13'
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
     The S13 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The thread the captured per-job forward peak into the memory budget as the maximum across the job's brackets and ## Scope

- `src/vaultspec_rag/memory_probe.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# thread the captured per-job forward peak into the memory budget as the maximum across the job's brackets

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Add `record_forward_peak_mb` to `MemoryBudget` in `src/vaultspec_rag/memory_probe.py`: thread-safe maximum accumulation of lock-bracketed forward peaks into the job's own budget.
- Add the thread-local `record_forward_peaks` router; the code consumer thread registers it around `encode_and_upsert_code_slice` in `src/vaultspec_rag/indexer/_codebase_indexer.py`, and the document path registers it around `encode_and_upsert_document_slice` in `src/vaultspec_rag/indexer/_document_indexer.py`.

## Outcome

Attribution is by thread: a job's forwards run on the thread that entered its recorder context, so a completed bracket credits the owning job and no other. The retained value is the maximum across all of the job's brackets.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

None.
