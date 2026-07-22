---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S25'
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
     The S25 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Stream metadata rows and deterministic point identities through the ledger contract and ## Scope

- `src/vaultspec_rag/indexer/_code_meta.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Stream metadata rows and deterministic point identities through the ledger contract

## Scope

- `src/vaultspec_rag/indexer/_code_meta.py`

## Description

- Stream ordered, converged ledger file states into an fsynced atomic metadata replacement.
- Stamp published metadata with the generation, membership epoch, and content epoch.
- Publish a generation only after metadata publication succeeds.
- Carry compatible published manifests across operational pipeline-sizing changes while retaining exact attempt-resume compatibility.
- Record storage-confirmed stale deletions after replacement upserts complete.

## Outcome

Full, unscoped incremental, and scoped incremental code indexing now publish deterministic file and point evidence through the ledger contract. Operational queue and segment tuning starts a fresh attempt without discarding a content-compatible published manifest, and replacement recovery records stale-ID deletion after the new path is durably indexed.

## Notes

The initial phase boundary exposed two compatibility-ordering defects: pipeline sizing prevented manifest carry-forward, and stale-deletion evidence was rejected after a replacement path reached its indexed state. Both were corrected and covered by real SQLite and real storage/embedding behavior. Final verification passed 19 tests; no tests were skipped or marked as expected failures.
