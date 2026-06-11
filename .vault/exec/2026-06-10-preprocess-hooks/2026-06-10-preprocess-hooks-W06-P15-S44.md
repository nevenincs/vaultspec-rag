---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S44'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Index and search the toy project on real GPU, confirming anchors/locators and skip visibility (D11, D12)

## Scope

- `vaultspec-rag index/search (manual)`

## Description

Indexed a fresh toy workspace in-process on real GPU (`index --type code --rebuild --port <dead> --allow-fallback --json`) and searched it. The first attempt delegated to the
already-running resident service (production-like async job path), confirming delegation;
the in-process run then validated the current code.

## Outcome

`index --json` reported `added: 5`, `preprocess_skipped: 1`, and
`preprocess_failures: ["corpus/broken_doc.pdf: preprocessor exited 7: "]` - the D11
no-swallow counter surfaced through the real CLI. `search "revenue margin expansion"`
returned the extracted PDF unit at score 0.99 as the top hit, with `--json` carrying
`anchor=...#page=1`, `locator="page 1"`, `source_path`, and `preprocessor_id=toy-pdf`. The
broken PDF was correctly skipped, not indexed.

## Notes

**Finding (fixed):** the human-facing CLI results *table* has its own render loop in
`cli/_search.py` (separate from `cli/_render.py`) that surfaced only `path:line` and omitted
the anchor/locator. Fixed to prefer the deep-link anchor, then `path (locator)`, then
`path:line` - so the table now shows `report.pdf#page=1` for preprocess hits. The `--json`
and MCP surfaces already carried the fields correctly. This gap was invisible to the unit
suite and only surfaced by driving the real CLI - the point of this wave.
