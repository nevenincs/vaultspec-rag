---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S02'
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
     The S02 and 2026-06-27-rag-broker-affordances-plan placeholders are machine-filled by
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
     The Reorder service_start so the idempotent already-running check precedes the port and machine guards and ## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Reorder service_start so the idempotent already-running check precedes the port and machine guards

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Moved the `_existing_service_running()` idempotent check to the TOP of `service_start`, ahead of the port and machine guards: a healthy owned service is now `already_running` (success) before the guards, instead of tripping the port-guard exit 1 first.
- Removed the now-redundant late `if _existing_service_running(): return`.

## Outcome

The friendly idempotent path is no longer shadowed: an already-running owned service exits 0, while the port and machine guards still catch the genuine "a foreign process holds the port" / "another service owns the machine" cases.

## Notes

The reorder is safe because the guards only need to catch NON-our-service conditions, which the idempotent check (identity + health) already excludes.
