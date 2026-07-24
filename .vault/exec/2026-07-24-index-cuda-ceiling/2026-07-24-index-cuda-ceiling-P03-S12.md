---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S12'
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
     The S12 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The capture the allocation high-water inside the gpu_lock forward bracket in the shared encode path and ## Scope

- `src/vaultspec_rag/indexer/_streaming.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# capture the allocation high-water inside the gpu_lock forward bracket in the shared encode path

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Place the `cuda_forward_peak_capture` bracket inside the lock-held forward paths in `src/vaultspec_rag/embeddings.py`: the on-device dense encode (which the streaming caller invokes while holding `gpu_lock`) and the sparse encode's own `with gpu_lock:` block.
- Leave the unserialised no-lock sparse branch and the CPU-output dense path unbracketed: without the lock a rebase could race a concurrent bracket.

## Outcome

Every serialised indexing forward rebases and reads the peak counter inside the critical section, so the captured value is that forward's own demand and never a sibling's. The capture also completes on an exceptional exit, so an allocator OOM still records the demand that triggered it.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

The planned locator for this step was `src/vaultspec_rag/indexer/_streaming.py`, but that file is held dirty by a concurrent session. The bracket landed in `src/vaultspec_rag/embeddings.py` instead, which is equivalent: the dense on-device encode body executes entirely within the caller's `gpu_lock` hold, and the sparse lock acquisition already lives in `embeddings.py`. No edit to `_streaming.py` was made or needed.
