---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S33'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Implement the stdlib html.parser strip with raw-markup fallback and thread html_strip into the worker (D13)

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

Added `indexer/_html.py`: a stdlib `html.parser.HTMLParser` subclass that drops
script/style/head bodies, emits newlines on block-level tags so the splitter keeps
structure, decodes entities, and collapses blank lines. The worker's `_chunk_decoded` calls
it for `.html` sources when `html_strip` is on, before `chunk_with_splitter`, with a
raw-markup fallback on any parse error. `html_strip` is resolved in the worker via
`_resolve_html_strip()` (config env+default, spawn-inherited) (D13).

## Outcome

HTML indexes as clean text by default; no new dependency; worker stays torch-free.

## Notes

stdlib-only (no bs4/lxml); fallback guarantees HTML indexing never regresses.
