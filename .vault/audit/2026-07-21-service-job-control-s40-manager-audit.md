---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-W01-P18-S40]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

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
