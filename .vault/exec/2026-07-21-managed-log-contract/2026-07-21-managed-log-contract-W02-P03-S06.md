---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S06'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace managed-log-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S06 and 2026-07-21-managed-log-contract-plan placeholders are machine-filled by
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
     The Replace the legacy service-only reader with bounded source-aware grouped log retrieval and ## Scope

- `src/vaultspec_rag/logging_config.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Replace the legacy service-only reader with bounded source-aware grouped log retrieval

## Scope

- `src/vaultspec_rag/logging_config.py`

## Description

- Replace the service-only reader with source-aware managed-log retrieval.
- Discover sparse numeric generations and reverse-read bounded blocks.
- Preserve independent per-source limits, order, and empty groups.

## Outcome

Operators can retrieve bounded service, Qdrant, or grouped all-source records without whole-file loading.

## Notes

Read and rollover races degrade to the available records instead of fabricating data.
