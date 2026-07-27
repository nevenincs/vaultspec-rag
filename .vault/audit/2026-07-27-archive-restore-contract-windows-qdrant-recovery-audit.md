---
tags:
  - '#audit'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace archive-restore-contract with a kebab-case feature tag, e.g. #foo-bar.
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

# `archive-restore-contract` audit: `windows qdrant recovery`

## Scope

Real archive restoration against the pinned Windows Qdrant server.

## Findings

### windows-qdrant-recovery | high | pinned server cannot complete archive recovery

The real 1.18.2 server accepted both a local-file recovery request and the
OpenAPI upload surface, then failed while syncing its internally generated
`replica_state.json` below its recovery temporary directory with Windows access
denied error 5. The failure reproduced outside pytest after a successful real
archive and source deletion. The reader, preview, refusal, rollback, and
provenance paths remain covered, but a successful restore cannot be claimed on
this pinned Windows runtime.

## Recommendations

- Decide the supported Windows Qdrant recovery runtime or upstream remediation
  before closing the blocked real-restore steps.
