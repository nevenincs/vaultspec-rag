---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S41'
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
     The S41 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Measure source bytes, files, generated chunks, and weighted units without materializing the corpus and ## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Measure source bytes, files, generated chunks, and weighted units without materializing the corpus

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Accumulate admitted source-file and source-byte dimensions during policy discovery.
- Carry exact full and scoped measurements in immutable preflight authorities.
- Accumulate generated chunks and conservative weighted bytes as bounded file segments are produced.
- Reject the first exceeded runtime dimension before its segment enters the GPU queue.

## Outcome

Code workloads expose exact source dimensions before execution and exact generated dimensions during bounded production. Measurement retains only counters plus the active segment; it never materializes source contents or a corpus-wide chunk collection.

## Notes

Both full and scoped discovery count only paths admitted to the code domain. Runtime measurement includes already-confirmed replay segments so the support contract describes the complete generated workload rather than only work remaining after restart.
