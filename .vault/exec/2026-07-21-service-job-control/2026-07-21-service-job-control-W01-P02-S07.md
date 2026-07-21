---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S07'
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
     The S07 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Implement atomic durable-before-dispatch persistence and queued, paused, and interrupted restart recovery using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement atomic durable-before-dispatch persistence and queued, paused, and interrupted restart recovery using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Add an injectable manager state path so real tests and managed service storage remain isolated.
- Serialize canonical active resources and active idempotency bindings through one versioned schema.
- Flush and atomically replace the state file before admitting, dispatching, or applying lifecycle changes.
- Roll back in-memory mutations when durable state cannot be committed.
- Restore queued and paused resources under the same IDs and convert prior live attempts to immutable interrupted history.
- Reject corrupt, incompatible, duplicate, or over-capacity persisted state without partial application.

## Outcome

Managed jobs now have one crash-safe persistence boundary. Accepted queued work is durable
before it can run, paused intent survives restart, and unacknowledged live work returns as
truthful interrupted history instead of disappearing or being mislabeled cancelled.

## Notes

Ruff, formatting, `ty`, strict BasedPyright, and all 49 focused unit tests passed. Real
temporary-directory probes verified atomic replacement, queued/paused/live recovery,
idempotency replay, corrupt-file isolation, absence of orphan temp files, and rollback when
the persistence parent cannot be created.
