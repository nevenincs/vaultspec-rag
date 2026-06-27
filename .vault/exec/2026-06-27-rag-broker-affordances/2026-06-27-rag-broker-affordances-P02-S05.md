---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S05'
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
     The S05 and 2026-06-27-rag-broker-affordances-plan placeholders are machine-filled by
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
     The Add machine_discovery_path and a tolerant read_machine_discovery to the machine-lock module and ## Scope

- `src/vaultspec_rag/_machine_lock.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add machine_discovery_path and a tolerant read_machine_discovery to the machine-lock module

## Scope

- `src/vaultspec_rag/_machine_lock.py`

## Description

- Added `machine_discovery_path()` (= `machine_lock_path().parent / "service.json"`, STATUS_DIR-independent, distinct from the per-STATUS_DIR file) and a tolerant `read_machine_discovery()` to `_machine_lock.py`, both exported in `__all__`.

## Outcome

The machine-global discovery pointer has a canonical path beside the lock and a reader that treats a missing/unreadable/non-object file as truthful absence (never raising), so a consumer finds the one service regardless of its own STATUS_DIR.

## Notes

Placed in `_machine_lock.py` (the existing machine-global-path owner) so it stays a neutral leaf the daemon and a consumer share.
