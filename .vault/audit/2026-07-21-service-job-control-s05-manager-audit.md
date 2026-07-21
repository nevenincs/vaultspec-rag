---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-service-job-control-plan]]"
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

# `service-job-control` audit: `W01.P02.S05 bounded job manager`

## Scope

Independent safety, intent, concurrency, and compatibility review of the final
`W01.P02.S05` manager implementation in `jobs.py`.

## Findings

<!-- A rolling log of findings: append one subsection per finding, grouped or ordered by
     severity, using the heading form

       ### W01.P02.S05 bounded job manager | {level} | {summary}

     followed by a paragraph carrying the detail. W01.P02.S05 bounded job manager is a concise kebab-case slug,
     {level} is the severity (critical, high, medium, low), and {summary} is a one-line
     statement. Append continuously as findings surface; do not rewrite settled entries. -->

### root-alias-deduplication | high | Lexical aliases could admit duplicate active work

The initial implementation normalized path spelling without resolving filesystem identity.
A symlink, junction, or Windows extended-path alias could therefore acquire a second slot
for the same storage root. The revision strips extended prefixes, resolves the root, and
normalizes case before keying active work. Resolution failures now return the structured
`invalid_project_root` outcome.

### maintenance-paused-admission | high | Maintenance could occupy an unmanageable paused slot

The initial create path allowed `start_paused` for maintenance even though maintenance
capabilities are neither pausable nor resumable. The revision rejects that request with the
structured `invalid_start_state` outcome.

Final re-review found no remaining critical, high, medium, or low issues. Extended-path
deduplication, mode conflict, capacity, maintenance, idempotency, real threaded ownership,
and real asyncio ownership probes passed. Ruff, ty, BasedPyright, 49 focused tests, and diff
checks passed.

Status: **PASS** after revision. There are no unresolved critical or high findings.

## Recommendations

Keep later transition and persistence Steps within this manager authority and directly
verify exact serialization, race outcomes, and terminal immutability in the planned tests.
