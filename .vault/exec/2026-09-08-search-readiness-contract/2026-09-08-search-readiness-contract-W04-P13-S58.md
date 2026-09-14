---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-14'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:d2d4d124eea4a2374c67b18bcf599bc71638f8f75ab708bd1e70bc93c670f1e6'
step_id: 'S58'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---


# Document immediate and bounded policy states retries CLI and MCP automation examples

## Scope

- `docs/search-and-index.md`

## Changes

- `M` `docs/search-and-index.md`
- `verify:` `uv run mdformat --check docs/search-and-index.md` -> `pass`
- `verify:` `uv run vaultspec-rag search --help` -> `pass`
- `verify:` `ConvertFrom-Json <MCP example>` -> `pass`
- `verify:` `uv run pytest <CLI and MCP freshness contract cases> -q` -> `pass`
- `verify:` `git diff --check` -> `pass`
