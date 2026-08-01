---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
body_hash: 'sha256:9b5cc785a39b383ed8f25b7ff2df25479f5d6d23b756858400e3c17df188e2c2'
step_id: 'S27'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Render anchor and locator in the CLI result table (D12)

## Scope

- `src/vaultspec_rag/cli/_render.py`

## Description

The CLI results renderer's Location column now prefers the deep-link `anchor` when present
(e.g. `report.pdf#page=12`), falls back to `path (locator)` when only a locator is set, and
otherwise keeps the existing `path:line_start` for code (D12).

## Outcome

`vaultspec-rag search` shows source-addressed locations for preproc hits instead of a
meaningless `:0` line number.

## Notes

Renderer reads the serialized result dict, so it works for both in-process and via-MCP rows.
