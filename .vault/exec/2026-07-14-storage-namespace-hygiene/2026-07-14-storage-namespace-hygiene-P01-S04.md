---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S04'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-namespace-hygiene with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S04 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Serve the storage survey route from the snapshot with filters applied to the cached list, add computed_at and source envelope fields, and implement the fresh=true recompute-and-publish path and ## Scope

- `src/vaultspec_rag/server/_routes.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Serve the storage survey route from the snapshot with filters applied to the cached list, add computed_at and source envelope fields, and implement the fresh=true recompute-and-publish path

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Split the old `_gather_storage_survey` into `_fetch_surveys` (the O(namespaces) walk) and `_shape_survey_payload` (filters, limit, `queried_root`, freshness metadata) in `src/vaultspec_rag/server/_routes.py`
- Rebuild `_gather_storage_survey` as snapshot-first: cache hit shapes the cached list (`source: cache`), `fresh=True` or a cold slot runs the walk and republishes (`source: fresh`)
- Parse `?fresh=` on `storage_survey_route` (truthy set `1`/`true`/`yes`) and thread it through

## Outcome

The route is O(1) on the common path with `computed_at`/`source` in every envelope; the payload stays backward-compatible (new fields only). Commit 7ae79ca.

## Notes

Filters apply post-cache, so `?limit=` semantics are unchanged; `total` still counts post-filter namespaces.
