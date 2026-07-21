---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

# `service-job-control` `W01.P02` summary

The canonical job model, exact-ID manager, lifecycle protocol, and durable recovery authority
are implemented as one service-domain contract.

- Modified: `src/vaultspec_rag/jobs.py`

## Description

Immutable job specifications, resource and progress snapshots, revisioned views, structured
outcomes, capabilities, attempts, and canonical states now describe every managed job.
`JobManager` enforces bounded admission, normalized-root active-work deduplication, bounded
idempotency retention, exact task ownership, and bounded terminal history.

Pause, resume, cancellation, retry, deletion, acknowledgement, and first-terminal-writer-wins
transitions use optimistic revisions and deterministic ownership checks. Versioned persistence
uses atomic replacement and complete-generation validation; queued and paused work restores,
while crashed live attempts become retained `interrupted` history. The post-phase audit also
closed durability rollback, capability, resource acknowledgement, and restore-validation gaps.
