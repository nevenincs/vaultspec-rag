---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S04'
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
     The S04 and 2026-07-21-managed-log-contract-plan placeholders are machine-filled by
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
     The Implement bounded raw-byte rotation and configure the Qdrant supervisor from the shared retention policy and ## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement bounded raw-byte rotation and configure the Qdrant supervisor from the shared retention policy

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Add a secure append-only raw rotating sink for supervised child output.
- Rotate before writes, shift sparse numeric backups, prune stale generations, and support zero-backup truncation.
- Retain recent in-memory output when persistence fails.
- Keep a single-writer guard while an inherited pipe delays drain completion.

## Outcome

Qdrant output has finite independent retention without weakening supervisor diagnostics or writer exclusivity.

## Notes

Independent review found and closed a drain-lifecycle race and a cleanup escape before acceptance.
