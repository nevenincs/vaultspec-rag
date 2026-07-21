---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S01'
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
     The S01 and 2026-07-21-machine-discovery-recovery-plan placeholders are machine-filled by
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
     The Force status and Qdrant storage paths beneath one session-owned temporary root and reset cached configuration at every test boundary and ## Scope

- `src/vaultspec_rag/tests/conftest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Force status and Qdrant storage paths beneath one session-owned temporary root and reset cached configuration at every test boundary

## Scope

- `src/vaultspec_rag/tests/conftest.py`

## Description

- Force both singleton environment paths beneath one session-owned temporary root regardless of ambient values.
- Reset the core and RAG configuration caches on every force and restore boundary.
- Restore the canonical paths before and after every test and restore ambient values only after the session.
- Expose the canonical path mapping as an immutable view so fixture consumers cannot poison later rearming.
- Verify real heartbeat, discovery, identity, and lock paths remain inside pytest-owned storage.

## Outcome

The entire test session now owns both managed singleton paths. Missing, non-empty, or
cached path changes from one test cannot expose later tests to the operator's service
state, and the immutable session mapping preserves the rearm authority.

## Notes

Hostile-ambient and 24 focused real-behavior checks passed with the external trap
untouched. Ruff, targeted ty, strict BasedPyright, formatting, and diff checks passed.
The production fail-closed containment guard remains assigned to the next Step.
