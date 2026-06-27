---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S06'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace rag-broker-affordances with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S06 and 2026-06-27-rag-broker-affordances-plan placeholders are machine-filled by
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
     The Write the discovery payload to the machine-global pointer on the daemon heartbeat tick and clean it on shutdown and ## Scope

- `src/vaultspec_rag/server/_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Write the discovery payload to the machine-global pointer on the daemon heartbeat tick and clean it on shutdown

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Added `_write_machine_discovery` (atomic `.tmp` + `os.replace`, best-effort, debug-logged on failure) and called it from `_heartbeat_tick_sync` after the STATUS_DIR write, mirroring the same versioned payload to the machine-global pointer.
- Extended `_unlink_status_file_silently` to also remove the machine-global pointer on shutdown, so a stopped service leaves neither discovery file behind.

## Outcome

The daemon now advertises its coordinates at the STATUS_DIR-independent pointer on every heartbeat and cleans it on shutdown; the STATUS_DIR file and the lock authority are unchanged.

## Notes

The pointer write is best-effort (a failure never breaks the heartbeat); the STATUS_DIR file still describes the service and the OS lock remains the singleton authority.
