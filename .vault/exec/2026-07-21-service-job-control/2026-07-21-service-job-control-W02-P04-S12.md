---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S12'
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
     The S12 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Verify real streaming and vault indexing observe control between slices without exposing partial rebuilds using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify real streaming and vault indexing observe control between slices without exposing partial rebuilds using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

- Exercise production vault streaming with real files, local Qdrant, the real
  run-control token, and a CPU-backed production embedding path.
- Request pause and cancellation only after a slice is observably published,
  then verify streaming unwinds before publishing the complete corpus.
- Hold the real GPU lock across a clean rebuild, request pause after the
  collection is dropped inside the protected span, and verify the request
  remains pending until replacement points and metadata are complete.
- Verify formatting, static types, focused integration behavior, adjacent
  control/indexer regressions, and architecture constraints through independent
  review.

## Outcome

Production streaming now has deterministic integration coverage proving pause
and cancellation delivery between real one-document slices. Clean rebuild
coverage observes the actual empty collection while publication protection is
active and proves all document IDs, revised stored content, and the revised
metadata hash are published before pause acknowledgement.

Ruff, Ruff formatting, ty, strict BasedPyright, and `git diff --check` passed.
All 3 focused integration cases, 17 adjacent run-control cases, and 106 indexer
unit cases passed. Independent review found no Critical or High issues.

## Notes

The first collection attempt used pytest's reserved `request` parameter name;
renaming it to `control_request` resolved collection before production behavior
ran. The test model is a real CPU `SentenceTransformer` BoW backend invoked
through `EmbeddingModel.encode_documents`; it avoids the recorded CUDA OOM and
does not use a fake, stub, patch, or mirrored implementation.
