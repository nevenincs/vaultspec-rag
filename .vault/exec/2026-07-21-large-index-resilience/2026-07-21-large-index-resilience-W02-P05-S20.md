---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S20'
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
     The S20 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Implement the per-root SQLite run generation, signature, commit-unit, finalization, and compaction schema and ## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement the per-root SQLite run generation, signature, commit-unit, finalization, and compaction schema

## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py`

## Description

- Add a versioned per-root SQLite schema for generations, commit units, and explicit file outcomes.
- Canonicalize model, schema, policy, epoch, preprocessing, operation, and content-kind compatibility identity.
- Record storage-confirmed upsert and deletion segments transactionally with idempotent replay.
- Enforce ordered external finalization, immutable terminal generations, bounded row iteration, and post-publication compaction.
- Reject incompatible schemas, invalid transitions, and corrupt database state without authorizing skipped work.

## Outcome

Indexing now has a CPU-only transactional authority that can lag storage by one safely replayable unit but cannot claim an unconfirmed mutation. Compatible attempts resume their active generation; drift invalidates the prior generation before a replacement begins.

## Notes

The production pipeline integration remains owned by the subsequent resumable-pipeline phase. This step establishes the ledger contract without opening storage or importing GPU dependencies.
