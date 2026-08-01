---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:0629f5c1be85cec3beddb6c7a00cd9fb69a61cfa23eccc3aa6e54fb95b363706'
step_id: 'S07'
related:
  - "[[2026-07-23-index-job-backend-resilience-plan]]"
---

# Run the store and indexer test suites plus lint and type checks for the touched modules and record them green with no new suppressions

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Ran the full unit test suite rather than only the directly-touched modules.
- Ran ruff check and ruff format, both project type checkers, and the citation gate over the touched files.

## Outcome

All green with no new suppressions:

- Full unit suite: 1842 passed, 0 failed.
- `ruff check` and `ruff format --check` on the touched modules: clean.
- `ty check` over the package: all checks passed.
- `basedpyright` on the touched modules: 0 errors, 0 warnings, 0 notes.
- Citation gate: clean.

The full-suite run also surfaced two failures belonging to the sibling chunk-identifier work rather than to this feature: two tests parsed a code chunk id into colon-separated parts and asserted the pre-change three-part shape. They were corrected to the four-part form and to additionally assert that ordinals within a file never collide. Running only the directly-touched suites had missed them, which is why this step ran the whole suite.

## Notes

The lesson is recorded deliberately: verifying a step against only the modules it edits is insufficient when the change alters a value's shape, because the assertions that pin that shape can live in any suite.
