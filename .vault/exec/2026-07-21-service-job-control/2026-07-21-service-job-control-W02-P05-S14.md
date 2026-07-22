---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S14'
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
     The S14 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Protect code clean rebuild and per-file replacement spans from cooperative interruption until published state is valid using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Protect code clean rebuild and per-file replacement spans from cooperative interruption until published state is valid using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Protect clean code collection publication from immediately before drop
  through recreation, batched replacement, stale cleanup, and atomic metadata.
- Protect modified and deleted incremental change sets from old-chunk deletion
  through batched replacement and atomic metadata in both scoped and unscoped
  paths.
- Keep scanning, hashing, chunking, and old-ID discovery checkpointable outside
  destructive spans, and keep new-only publication interruptible between GPU
  slices.
- Preserve cross-file batching, progress phases, storage lock ordering, the
  single GPU consumer, CPU-only workers, and S13 cleanup and error precedence.

## Outcome

Pause and cancellation can no longer be deliberately delivered while a clean
code collection is absent or while modified files have been deleted but not yet
replaced. Requests already pending are rejected at the protected entry; requests
arriving during publication remain pending until the collection, replacements,
and metadata are valid. Application failures retain priority and remain visible.

Real production probes observed clean and scoped incremental requests inside the
destructive intervals and verified complete data and metadata before exact
`PauseRequested` delivery. Verification also passed 24 code/GPU/progress
integration tests, 126 unit/control/architecture tests, Ruff, Ruff format, ty,
BasedPyright, and `git diff --check`. Independent review finished at Critical 0
and High 0.

## Notes

The incremental protection intentionally covers the complete changed-file set
rather than fragmenting it into per-file GPU calls. This conservatively protects
every file's invalid interval while preserving the established cross-file batch
and progress contract; CPU preparation remains outside. The temporary probe was
removed. Semantic RAG refresh was not retried because the execution context
records a CUDA OOM for that path. S15 retains ownership of permanent integration
test additions and the Phase Summary.
