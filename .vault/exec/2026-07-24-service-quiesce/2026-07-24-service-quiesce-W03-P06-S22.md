---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S22'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S22 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Prove through the authenticated production routes, real registry, real manager writer, and real filesystem that an unpublished resume write returns resume_recovery_failed in closed warming, then directory repair and a second resume return running with the same logical job ID and one recovered generation and ## Scope

- `src/vaultspec_rag/tests/test_service_quiesce_routes.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove through the authenticated production routes, real registry, real manager writer, and real filesystem that an unpublished resume write returns resume_recovery_failed in closed warming, then directory repair and a second resume return running with the same logical job ID and one recovered generation

## Scope

- `src/vaultspec_rag/tests/test_service_quiesce_routes.py`

## Description

Exercise authenticated production resume routing with a real registry, real
manager persistence writer, real filesystem failure, and an adopted service
loop. Retain the failed desired-running job, repair the directory, and recover
one next attempt under the same logical identifier.

## Outcome

Satisfied by `0df85c2c`. The checked-in proof asserts exact failure and success
body shapes, closed warming admission after the unpublished write, same-ID
attempt progression from one to two, one recovered generation, and no pending
dispatch claim.

## Notes

The proof contains no fake, mock, stub, patch, monkeypatch, skip, or xfail. Its
recorded negative mutation targets the `retryable` assertion. The test was not
rerun during this static acceptance.
