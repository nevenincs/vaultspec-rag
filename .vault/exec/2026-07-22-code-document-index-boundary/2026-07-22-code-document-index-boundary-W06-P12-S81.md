---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S81'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S81 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Verify bounded document completion, interruption, and resume with representative real formats, extractor processes, CUDA, and Qdrant and ## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify bounded document completion, interruption, and resume with representative real formats, extractor processes, CUDA, and Qdrant

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py`

## Description

- Run real direct decoding and out-of-process extraction under one bounded profile.
- Interrupt after the first storage-confirmed document unit.
- Resume the same generation through CUDA embedding and local Qdrant publication.

## Outcome

The named acceptance workload completed four files and ten chunks. It resumed
the interrupted generation from one confirmed unit to ten without replaying
confirmed work. Peak RSS was 1,693,052,928 bytes and peak CUDA reservation was
1,927,282,688 bytes.

## Notes

The first sparse run exposed an observation-timeout ordering defect in the
harness before cancellation was requested. The corrected dense acceptance run
completed in 35.7 seconds against real CUDA and local Qdrant; all resources
were released afterward.
