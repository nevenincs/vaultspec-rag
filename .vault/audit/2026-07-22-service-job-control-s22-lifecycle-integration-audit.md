---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
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

# `service-job-control` audit: `S22 lifecycle integration`

## Scope

Audit `W03.P11.S22` coverage for real daemon restart and shutdown behavior in
`test_service_lifecycle.py`. The review covers durable queued and paused intent,
cooperative interruption after exact runtime-owner release, store-before-Qdrant
teardown ordering, restart reopening, process isolation, and compliance with the
project's real-behavior test policy.

## Findings

No pre-review finding is open. Independent review remains pending against the
frozen post-verification diff.

## Recommendations

Do not close the plan row or commit until an independent reviewer confirms zero
critical and high findings. Preserve the test-owned status, storage, port, model,
and process-group isolation in any revision.

## Verification evidence

- The two focused lifecycle cases pass together against real service processes,
  cached GPU models, the pinned manifest-backed Qdrant binary, production
  persistence decoding, production indexers, and real HTTP routes.
- The restart case crosses two daemon lives and observes the canonical manager
  restoring two active resources, dispatching only queued running intent, then
  restoring only the dormant paused resource on the second life.
- The shutdown case observes task, worker, limiter capacity, project lease,
  writer lock, and code pipeline ownership before signalling. It then observes
  terminal interruption only after all owners clear and the finished resource
  snapshot is durable.
- The shutdown log orders attempt completion before `ProjectSlot` closure,
  registry closure before the supervised Qdrant child stops, and clean service
  completion last. A second daemon opens the same isolated storage and serves a
  real code search.
- Ruff formatting and lint, BasedPyright, cognitive complexity, nesting depth,
  diff hygiene, and the prohibited-double scan pass. Changed functions have a
  maximum Xenon grade C and average grade A; the whole target file's existing
  baseline average remains grade B.
- Post-run process inspection finds no test-owned Python or Qdrant process, and
  the signalable fixture runs from its isolated temporary directory so Qdrant
  cannot publish a sentinel into the worktree.
