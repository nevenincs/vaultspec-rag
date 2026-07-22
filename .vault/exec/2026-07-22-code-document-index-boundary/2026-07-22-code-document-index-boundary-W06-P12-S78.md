---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S78'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S78 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Expose active source and document support profiles and their independent ceilings in service status and ## Scope

- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/server/_lifespan.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Expose active source and document support profiles and their independent ceilings in service status

## Scope

- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Project the configured support profile through the jobs service domain.
- Expose independent code and document ceilings at the health boundary.
- Verify all declared dimensions through a real HTTP health request.

## Outcome

Service status now reports the active named profile and separate code and
document limits for source files, source bytes, extracted bytes, generated
chunks, weighted work, queue bytes, RSS, and CUDA memory.

## Notes

Scoped Ruff and Ty checks passed. The targeted health test passed against the
real Starlette route.
