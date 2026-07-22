---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S99'
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
     The S99 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Include document collections in prefix pruning, debris classification, and storage maintenance routes and ## Scope

- `src/vaultspec_rag/storage_ops.py`
- `src/vaultspec_rag/server/_routes_storage.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Include document collections in prefix pruning, debris classification, and storage maintenance routes

## Scope

- `src/vaultspec_rag/storage_ops.py`
- `src/vaultspec_rag/server/_routes_storage.py`

## Description

- Make prefix archive and removal targets deterministic.
- Aggregate document points in backend maintenance totals.
- Expose per-domain counts through the bounded service survey route.

## Outcome

Storage maintenance treats document collections as first-class namespace
members without encoding repository paths or client-specific layout.

## Notes

Static lint and type checks passed. Real maintenance behavior is verified in S124.
