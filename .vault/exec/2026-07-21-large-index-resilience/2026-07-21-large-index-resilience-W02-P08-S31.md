---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S31'
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
     The S31 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Interrupt each finalization phase and prove restart converges to exact point IDs and metadata and ## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Interrupt each finalization phase and prove restart converges to exact point IDs and metadata

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Interrupt generations independently after stale reconciliation, metadata publication, and generation publication.
- Reopen each exact generation and resume only its remaining durable phases.
- Verify committed point identities remain attached to the resumed generation.
- Verify the atomic metadata sidecar exists before successful generation completion and compaction.

## Outcome

Every finalization interruption point converges through the same idempotent production methods to a compacted successful generation with retained point evidence and published metadata.

## Notes

The phase matrix uses real SQLite transactions and the production metadata publisher. Real-store full idempotence and clean-recovery cases provide the external storage convergence boundary without test doubles.
