---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S29'
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
     The S29 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Interrupt and restart a real multi-segment index and prove replay is limited to the last unrecorded unit and ## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Interrupt and restart a real multi-segment index and prove replay is limited to the last unrecorded unit

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Interrupt a real multi-unit code stream after production storage publishes durable work.
- Verify the consumer and worker pool unwind before the writer boundary is released.
- Resume against the same vector store and compatible generation.
- Combine real-store convergence with SQLite segment evidence proving committed units are skipped and only unconfirmed units remain eligible.

## Outcome

Interrupted code indexing preserves exact storage-confirmed progress, releases execution resources, and resumes to the current source state without restarting committed segment work. A storage/checkpoint crash gap remains bounded to replay of the single unrecorded idempotent unit.

## Notes

Acceptance uses the production weighted code pipeline, real vector storage, a production control token, and the transactional SQLite ledger. No fakes, mocks, patches, skips, or expected failures are used.
