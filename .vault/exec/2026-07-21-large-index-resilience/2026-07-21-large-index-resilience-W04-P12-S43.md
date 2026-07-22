---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S43'
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
     The S43 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Verify profile requirements, corpus limits, disk preflight, checkpoint preservation, and structured refusal and ## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify profile requirements, corpus limits, disk preflight, checkpoint preservation, and structured refusal

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Verify independent named profiles and every admission dimension.
- Verify discovery counts only admitted code source files and bytes.
- Verify generated-weight refusal occurs before an overweight segment is yielded.
- Verify HTTP refusal is structured and precedes durable job creation.
- Re-run real CUDA and Qdrant checkpoint-preservation boundaries.

## Outcome

The support-profile boundary is covered from immutable measurement through service refusal and resumable storage. Over-budget work is typed, no refused job is persisted, and confirmed checkpoint work survives control and clean-rebuild resume.

## Notes

The phase boundary passed 10 cases in 28.51 seconds, including real CUDA and Qdrant execution. Ruff, formatting, and static type checks passed. The repository-wide complexity hook still reports its broad pre-existing baseline offenders; no new failing assertion or type finding remained in this block.
