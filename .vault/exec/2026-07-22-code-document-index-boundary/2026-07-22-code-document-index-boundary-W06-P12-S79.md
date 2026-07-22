---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S79'
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
     The S79 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Generate a separately named document workload with measured source, extracted, chunk, queue, RSS, and CUDA dimensions and ## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Generate a separately named document workload with measured source, extracted, chunk, queue, RSS, and CUDA dimensions

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py`

## Description

- Generate marker-protected raw and extracted document inputs.
- Exercise production discovery, extraction, chunking, and weighted slicing.
- Report source, extracted, chunk, queue, RSS, and CUDA dimensions separately.

## Outcome

The document workload has a dedicated executable harness and machine-readable
measurement schema. Explicit route configuration owns every input; its layout
is only fixture organization and carries no admission semantics.

## Notes

Scoped Ruff and Ty checks passed. A unique marker-owned root completed the
prepare-only CPU boundary with the requested file and byte counts. The measured
production run is serialized with the phase GPU boundary.
