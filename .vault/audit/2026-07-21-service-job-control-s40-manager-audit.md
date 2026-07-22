---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-W01-P18-S40]]"
---

# `service-job-control` audit: `S40 manager extraction`

## Scope

Audited the S40 extraction of canonical `JobManager` ownership and private runtime
types, the one-way dependency boundary, the `jobs` compatibility facade, shared
retention default, logger identity, and real-behavior regression coverage.

## Findings

### fresh-interpreter-worktree-resolution | high | Boundary probe resolved another editable worktree

The initial subprocess regression inherited the active environment's editable
package resolution and could import a different worktree. The revision explicitly
prepends the current test file's `src` directory before either production import.
The shared-main-venv reproduction and the isolated test run now both pass.

### manager-extraction | low | Compatibility behavior remained byte-for-byte equivalent

Independent comparison found the extracted manager body and every retained legacy
dispatch function equivalent to committed S39. `job_manager` has no reverse import
of `jobs`; the facade re-exports the exact manager object and the sole
`MAX_RECORDS` value; both modules continue logging manager failures through
`vaultspec_rag.jobs`.

## Recommendations

Keep new service-domain orchestration in `job_manager` and preserve `jobs` only as
the compatibility and legacy dispatch surface. Keep isolated subprocess regressions
anchored to their own source root when multiple editable worktrees share an
interpreter environment.

## Status

PASS. The High test-harness finding was resolved, and independent re-review found
no remaining Critical or High findings. Ruff, ty, strict BasedPyright, 77 focused
unit and persistence tests, and 20 non-GPU jobs registry integration tests passed.
