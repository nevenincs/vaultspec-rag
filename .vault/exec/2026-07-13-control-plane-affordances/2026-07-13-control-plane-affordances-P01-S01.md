---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S01'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace control-plane-affordances with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S01 and 2026-07-13-control-plane-affordances-plan placeholders are machine-filled by
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
     The Extend the storage survey route to accept an optional root query parameter, resolve it through root_collection_prefix, narrow the namespace list to the matching prefix, and add the top-level queried_root object (present only when root is passed, returned even for unindexed roots) and ## Scope

- `src/vaultspec_rag/server/_routes.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Extend the storage survey route to accept an optional root query parameter, resolve it through root_collection_prefix, narrow the namespace list to the matching prefix, and add the top-level queried_root object (present only when root is passed, returned even for unindexed roots)

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Extend `_gather_storage_survey` with an optional `root` argument: resolve
  the queried root through `root_collection_prefix` (the one real
  derivation), narrow the namespace list to the matching prefix, and attach
  a top-level `queried_root` object `{root, prefix}` to the payload only
  when a root was queried.
- Parse the `?root=` query parameter in `storage_survey_route`, rejecting an
  empty/whitespace value with the existing `bad_request` 400 shape.
- Update route and gatherer docstrings to document the root-scoped lookup
  and the unindexed-root (empty namespaces, prefix still returned) contract.

## Outcome

Route-side lookup complete: `GET /storage/survey?root=<path>` answers with
the authoritative prefix even for a root absent from the manifest. Ruff,
ruff format, and basedpyright clean on the touched module.

## Notes

None.
