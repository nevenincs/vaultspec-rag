---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S07'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace machine-discovery-recovery with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S07 and 2026-07-21-machine-discovery-recovery-plan placeholders are machine-filled by
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
     The Thread the retained lease through startup and quiesce heartbeat before owner cleanup and lock release and ## Scope

- `src/vaultspec_rag/server/_lifespan.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Thread the retained lease through startup and quiesce heartbeat before owner cleanup and lock release

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Acquire one retained `MachineLockLease` before any subordinate component starts and pass
  its publisher through phase stamping, Qdrant identity publication, the heartbeat loop,
  and shutdown.
- Replace read-before-merge heartbeat and unauthenticated deletion paths with complete
  owner-authenticated snapshots and publisher-owned cleanup.
- Quiesce the synchronous publisher before cancelling periodic tasks so an already-running
  worker finishes behind the same guard and every later tick is inert.
- Delete both discovery views before releasing the singleton, and retain the lease for the
  registered exit retry when either deletion fails.
- Migrate focused production tests from mutable module patching to real isolated locks,
  paths, status locks, and owner publishers.

## Outcome

The daemon now carries one unforgeable lease from singleton acquisition through final
cleanup. Normal shutdown cannot release ownership while a heartbeat can still publish, and
it cannot admit a successor beneath stale discovery when owner cleanup fails.

## Notes

Ruff formatting and lint passed across all nine affected files, BasedPyright reported zero
diagnostics, and the focused real-behavior suite passed 23 tests. A broader server run also
passed 133 tests; its three failures belong to the concurrently open mandatory-preflight
contract remediation and are not used as S07 evidence. No operator daemon or managed
storage was touched.
