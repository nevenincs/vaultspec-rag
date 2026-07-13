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
