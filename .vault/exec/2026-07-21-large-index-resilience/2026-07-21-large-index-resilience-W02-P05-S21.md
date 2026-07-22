---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S21'
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
     The S21 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Verify atomic transactions, row-wise iteration, compatibility rejection, corruption handling, and immutable completion and ## Scope

- `src/vaultspec_rag/tests/test_index_run_ledger.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify atomic transactions, row-wise iteration, compatibility rejection, corruption handling, and immutable completion

## Scope

- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Description

- Exercise active-generation resume and compatibility-drift invalidation against a real SQLite file.
- Verify transactional commit-unit replay, segment completion, deletion units, and bounded row iteration.
- Verify explicit converged and unresolved file outcomes and ordered immutable finalization.
- Verify compaction preserves the published generation and independent running content-domain generations.
- Verify unsupported schema versions and corrupt database bytes fail closed.

## Outcome

Five imported-behavior tests pass against production ledger transactions. They establish idempotency, atomic rollback, immutable completion, compatibility rejection, corruption handling, and collection-independent generation retention without test doubles.

## Notes

The phase boundary passed Ruff, Ty, diff validation, and all ledger tests.
