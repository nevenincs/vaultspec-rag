---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S06'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-orphan-reaping with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S06 and 2026-07-23-service-orphan-reaping-plan placeholders are machine-filled by
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
     The Add the daemon-signature enumeration and the lock-and-pointer-anchored reap predicate and ## Scope

- `src/vaultspec_rag/cli/_service_stop.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the daemon-signature enumeration and the lock-and-pointer-anchored reap predicate

## Scope

- `src/vaultspec_rag/cli/_service_stop.py`

## Description

- Add `_orphan_daemon_pids` enumerating `vaultspec_rag.server` daemons via
  `psutil.process_iter`, matching the resident-daemon launch witness `-m vaultspec_rag.server --port <port>` (any launch token).
- Add `_reap_orphan_daemons` applying the safety predicate: reap a match only
  when it is not the machine-lock holder, not the discovery-pointer pid, and
  not this process, re-confirmed via `_is_our_service` and reaped by
  `_terminate_and_confirm` (which runs the unisolated-test refusal guard).

## Outcome

The reap targets only same-port race-losers; the port witness structurally
excludes isolated-config and foreign-worktree daemons (different port), and the
lock/pointer anchors spare the live singleton. ruff, ty, basedpyright clean and
the reap functions are complexity-clean. Landed with S07 in commit `eb669da3`.

## Notes

The port-witness match assumes the launcher partner in the launcher+daemon pair
also carries `--port`; P01 confirms this and the match is refined there if not.
The global complexity gate is red on another session's uncommitted
`_store_writes.py` (unrelated to this change).
