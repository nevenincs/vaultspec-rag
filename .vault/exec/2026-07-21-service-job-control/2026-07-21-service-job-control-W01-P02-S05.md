---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S05'
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
     The S05 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Implement exact-ID active and runtime ownership, bounded terminal history, admission, active-work deduplication, and idempotency keys using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement exact-ID active and runtime ownership, bounded terminal history, admission, active-work deduplication, and idempotency keys using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Add one thread-safe `JobManager` with independent active and terminal ownership.
- Keep nonterminal jobs exact-addressable and refuse admission at the configured bound.
- Replay idempotent creates, reject key reuse with changed input, and deduplicate equivalent active work before capacity checks.
- Retain task and cooperative-control references by exact job ID and release them only when the owning task identity matches.
- Bound terminal history independently and expire its associated idempotency bindings on eviction.

## Outcome

The service domain now owns canonical job resources through an admission-safe manager.
Controllable work cannot be evicted by history growth, repeated submissions resolve to
the same logical resource, and stale attempt cleanup cannot detach a newer runtime.

## Notes

Ruff and `ty` passed, as did a real concurrent submission probe covering exact-ID
lookup and active-work deduplication. The existing focused suites passed 56 tests; two
live-service fixture setups were unavailable because this worktree has no provisioned
Qdrant server binary, before either job-registry test body ran.
