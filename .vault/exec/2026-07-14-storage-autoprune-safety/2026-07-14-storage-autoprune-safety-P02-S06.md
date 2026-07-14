---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S06'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-autoprune-safety with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S06 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
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
     The Start and cancel the maintenance task in the daemon lifespan, delayed one interval after startup and gated on server mode plus the storage_autoprune knob and ## Scope

- `src/vaultspec_rag/server/_lifespan.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Start and cancel the maintenance task in the daemon lifespan, delayed one interval after startup and gated on server mode plus the storage_autoprune knob

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Generalize the lifespan's single heartbeat task handoff to a list of
  periodic tasks; `_shutdown_components` cancels and awaits each in order.
- Create the maintenance task at startup only when
  `effective_server_mode()` and the `storage_autoprune` knob are both on
  (the tick re-checks both cheaply, so a config flip is honoured either
  way); the loop itself delays the first cycle one full interval.

## Outcome

Server + machine-lock lifespan suites pass (121 tests); ruff, ruff
format, and basedpyright clean.

## Notes

None.
