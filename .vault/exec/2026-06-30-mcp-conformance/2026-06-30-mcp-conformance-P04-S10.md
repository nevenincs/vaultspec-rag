---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
body_hash: 'sha256:192f2ce62c47eb20156dd4e32329de1a4961d57a7fb29ec1d695f7f4bc9ca20c'
step_id: 'S10'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Align the MCP search default result count with the CLI default

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

Aligned the MCP search default with the CLI.

## Outcome

`top_k` defaults to 10 (`_DEFAULT_TOP_K`), matching the CLI `--max-results`, so the same query returns the same hit count on both surfaces.

## Notes

Asserted by `test_search_default_top_k_matches_cli_default`.
