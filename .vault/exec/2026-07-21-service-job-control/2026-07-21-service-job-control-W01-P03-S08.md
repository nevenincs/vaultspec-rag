---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S08'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S08 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Verify the transition matrix, idempotency, stale revisions, admission, deduplication, retry, deletion, and terminal immutability using vaultspec-standard-executor and ## Scope

- `src/vaultspec_rag/tests/test_jobs_unit.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify the transition matrix, idempotency, stale revisions, admission, deduplication, retry, deletion, and terminal immutability using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/test_jobs_unit.py`

## Description

- Drive concurrent equivalent submissions through the production manager and verify one exact resource owns them.
- Verify admission refusal, full-ID lookup, idempotency replay, and conflicting key reuse.
- Exercise stale revision handling, immediate queued pause, resume attempt lineage, and delivered pause/resume races.
- Exercise immediate and cooperative cancellation, pause/cancel precedence, and terminal transition rejection.
- Verify first-terminal-writer-wins, linked retry, force refusal, and terminal-only deletion.

## Outcome

The manager's public lifecycle contract is covered by real threads and asyncio tasks. The
tests prove that contention does not duplicate logical work, stale callbacks do not rewrite
new attempts, cancellation remains absorbing, and terminal history stays immutable.

## Notes

All five new managed-job tests passed. Ruff, formatting, `ty`, and strict BasedPyright also
passed for the expanded unit module; no fakes, mocks, patches, skips, or mirrored business
logic were introduced.
