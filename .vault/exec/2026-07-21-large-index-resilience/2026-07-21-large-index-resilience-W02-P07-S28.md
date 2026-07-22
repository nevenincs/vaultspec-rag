---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S28'
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
     The S28 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Persist clean-rebuild destructive intent and resume incomplete replacement generations without a second drop and ## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Persist clean-rebuild destructive intent and resume incomplete replacement generations without a second drop

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Persist clean destructive intent in the generation before collection replacement.
- Classify interrupted destructive attempts as `rebuild_incomplete` without masking the original failure.
- Resume matching incomplete generations and skip the collection drop when storage-confirmed units already exist.
- Preserve the cache-lifecycle boundary independently from code collection replacement.

## Outcome

An interrupted clean code rebuild retains one durable generation and resumes its confirmed segments against the existing replacement collection. Recovery no longer repeats the destructive drop or restarts completed segment work.

## Notes

The real-store recovery test seeded production-segment identities, marked the clean generation incomplete, resumed through `full_index(clean=True)`, and verified the exact confirmed point set survived. Ruff and ty passed for the changed implementation and test.
