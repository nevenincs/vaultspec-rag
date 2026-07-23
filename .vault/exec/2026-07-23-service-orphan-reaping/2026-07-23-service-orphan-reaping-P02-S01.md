---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S01'
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
     The S01 and 2026-07-23-service-orphan-reaping-plan placeholders are machine-filled by
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
     The Move the machine-singleton claim inside the lifespan startup try-guard so its failure routes through \_exit_standalone_daemon and ## Scope

- `src/vaultspec_rag/server/_lifespan.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Move the machine-singleton claim inside the lifespan startup try-guard so its failure routes through \_exit_standalone_daemon

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Move the `_claim_machine_singleton` call, and the `_DiscoveryPublisher` plus
  daemon-shutdown-hook construction it feeds, from before the lifespan startup
  guard to the top of the guarded `try`.
- Initialise `discovery` to `None` ahead of the guard so the failure branch can
  distinguish a lost claim (no lease, nothing to release) from a mid-startup
  failure.

## Outcome

A machine-singleton claim that loses the race now raises inside the guard and
routes through `_exit_standalone_daemon(1)` (the daemon's `os._exit`) instead of
escaping to uvicorn, where `uvicorn.run` returned and the interpreter-exit join
wedged the daemon alive. ruff, ty, and basedpyright clean; the server module
imports and the lifecycle-helper unit tests pass. Landed with S03 in commit
`57bdee8f`.

## Notes

Coupled with S03 - the teardown must tolerate `discovery is None` - so both land
in one commit. The bidirectional guard test (S05) proving a real race-loser
terminates is deferred to a GPU-free daemon-spawning window per the execution
sequencing.
