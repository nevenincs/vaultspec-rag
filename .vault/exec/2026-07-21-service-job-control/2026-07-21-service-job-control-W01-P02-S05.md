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

- Add one lazy process-wide manager with exact active, terminal, runtime, and control ownership.
- Refuse admission at the configured nonterminal bound without evicting controllable work.
- Deduplicate active work by resolved root and source identity and reject conflicting modes or desired states.
- Retain bounded idempotency replay records and return structured conflicts for reused keys.
- Hold strong task and worker references and revise immutable runtime snapshots on ownership changes.
- Guard terminal retention until every runtime and execution-resource flag is released.

## Outcome

The service domain now owns an exact-addressable, bounded job registry that cannot lose
nonterminal work to history eviction. Equivalent root aliases converge on one active slot,
create retries are idempotent, and runtime ownership remains strongly held until explicit
release.

## Notes

Independent review first found two High defects: lexical root aliases could bypass
deduplication, and maintenance could be admitted paused despite having no control
capabilities. Both were corrected; root-resolution errors are also structured instead of
escaping admission. Final review passed. Ruff, ty, BasedPyright, diff checks, real threaded
and asyncio probes, and 49 focused tests passed.
