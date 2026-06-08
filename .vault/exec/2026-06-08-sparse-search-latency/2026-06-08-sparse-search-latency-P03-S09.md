---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-08'
step_id: 'S09'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
  - '[[2026-06-08-comprehensive-code-review]]'
---

# sparse-search-latency P03.S09: Resolve any identified CRITICAL/HIGH issues

## Description

- Refactored `src/vaultspec_rag/store.py` to only acquire `_client_lock` locally around Qdrant scroll calls to avoid blocking the daemon during large index pagination.
- Introduced `VaultGraphError` in `src/vaultspec_rag/search/_searcher.py` and raised it instead of silently swallowing exceptions when graph build fails, ensuring errors can be correctly surfaced and monitored.
- Modified `src/vaultspec_rag/indexer/_streaming.py` to respect the `sparse_enabled` configuration rather than unconditionally computing SPLADE vectors on every indexing run.
- Rewrote MCP tools (`benchmark`, `quality`, and `get_logs`) in `src/vaultspec_rag/mcp/_admin_tools.py` to call daemon REST endpoints instead of running inline, solving process conflation and Qdrant database lock violations.
- Added `/benchmark`, `/quality`, and `/logs/json` endpoints to `src/vaultspec_rag/server/_routes.py` to support these refactored MCP tools cleanly over the REST API boundary.

## Outcome

All four CRITICAL/HIGH review issues have been successfully addressed.
The daemon process operates without excessive locking, avoids unauthorized local process collisions from MCP tools, properly gates sparse GPU compute by configuration, and exposes failures meaningfully.

## Notes

No critical incidents.
