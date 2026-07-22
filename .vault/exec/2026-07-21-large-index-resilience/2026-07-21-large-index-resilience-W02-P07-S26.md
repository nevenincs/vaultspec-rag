---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S26'
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
     The S26 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Implement idempotent stale-identity reconciliation and generation publication phases and ## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement idempotent stale-identity reconciliation and generation publication phases

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Resume ingestion-complete generations directly at their durable finalization phase.
- Make metadata and generation publication idempotent across stale-reconciled, metadata-published, generation-published, and compacted phases.
- Prevent full, unscoped incremental, and scoped incremental retries from re-entering storage ingestion after finalization begins.

## Outcome

Interrupted code generations now continue from the ledger's exact publication phase without replaying completed ingestion or attempting illegal file-state mutations. Generation success and compaction remain ordered after durable metadata publication.

## Notes

Focused verification passed seven checkpoint cases, including real SQLite recovery from each interruptible finalization phase. Ruff and ty passed for all changed modules.
