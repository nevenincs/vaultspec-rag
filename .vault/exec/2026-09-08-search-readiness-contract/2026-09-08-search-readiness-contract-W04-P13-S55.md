---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-14'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:a8a924f50a4f284a62e9bd1ea6409e25f76ce704e036d7998e04482145eed75e'
step_id: 'S55'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---


# Run focused unit integration MCP conformance concurrency guard and benchmark gates with individual exit codes

## Scope

- `src/vaultspec_rag/tests`

## Changes

- `verify:` `uv run pytest <readiness availability outcomes unit set> -q` -> `pass`
- `verify:` `uv run pytest <HTTP CLI routing set> -q` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_mcp_conformance_surface.py -q` -> `pass`
- `verify:` `uv run pytest <search activity and diagnostics concurrency set> -q` -> `pass`
- `verify:` `uv run pytest <resident-service readiness integration set> -q` -> `fail`
- `verify:` `uv run python -c <readiness control benchmark assertions>` -> `pass`

## Notes

The resident-service integration selection exited 1 before collection because no compatible
machine-pointer GPU service was captured. The CPU-only integration result-shape file passed in
S54; no GPU service was started for this Step.
