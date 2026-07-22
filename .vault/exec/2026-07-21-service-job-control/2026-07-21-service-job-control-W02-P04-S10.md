---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S10'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S10 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Thread run control through streaming embedding and check before and after bounded GPU slices outside gpu_lock using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/indexer/_streaming.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Thread run control through streaming embedding and check before and after bounded GPU slices outside gpu_lock using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Add no-op-default run-control parameters to the vault, code-slice, and codebase
  streaming helpers.
- Check cooperative control immediately before and after each bounded GPU encode
  slice, outside `gpu_lock` and before vector or storage mutation.
- Forward codebase stream control into the reusable single-slice encoder while
  preserving every existing caller.
- Verify formatting, static types, torch-free import behavior, control primitives,
  cleanup safety, and the focused source diff.
- Obtain an independent concurrency and safety review.

## Outcome

Streaming embedding now exposes the accepted cooperative control seam without
changing unmanaged indexing behavior. A pending pause or cancellation is delivered
before GPU acquisition or after the bounded forward slice has released `gpu_lock`;
post-encode delivery occurs before chunks are mutated or upserted.

Ruff, Ruff formatting, ty, and strict BasedPyright passed. All 17 production
run-control tests passed, the fresh-interpreter import remained torch-free, signature
defaults resolved to `NO_RUN_CONTROL`, and `git diff --check` passed. Independent
review found no Critical or High issues.

## Notes

Semantic discovery reported that this worktree had no indexed source sections, so
the step was grounded through full-file inspection and targeted source search. The
known CUDA OOM refresh was not retried. Real streaming interruption scenarios remain
assigned to S12 by the approved plan.
