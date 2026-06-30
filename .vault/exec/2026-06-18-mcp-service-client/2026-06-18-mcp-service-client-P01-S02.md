---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Create the import-light service-client transport housing the HTTP call primitive and the search, reindex, and admin client functions

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Move the production-proven HTTP wire client out of the CLI HTTP-search module into the new import-light transport module: `_do_http_call`, `_try_http_search`, `_try_http_reindex`, `_try_http_admin`, and every private helper they need (`_route_admin_tool`, `_logs_route_path`, `_admin_url_with_root`, the timeout/refused/diagnostics helpers, and the search-payload builder).
- Replace the CLI-coupled `_core.logger` with a module-local `logging.getLogger(__name__)` so the transport carries no dependency on the CLI runtime state.
- Point `_do_http_call` at the new discovery module for the status-file read instead of the old CLI service-status module.
- Import the lightweight filter validator from the `search` leaf validation module rather than the `search` package, so the transport never triggers the heavy searcher import chain.

## Outcome

- The transport module imports only stdlib plus the leaf validation module; importing it pulls no Torch, models, store, `api`, `indexer`, or `embeddings`.
- The function bodies are carried over verbatim in behavior, so the trinary "unreachable -> None / success dict / structured error dict" contract is preserved for search, reindex, and admin calls.
- The CLI tests that import these names and the routing test that exercises the logs-route builder stay green after the CLI module re-exports the moved functions.

## Notes

Decision on the `validate_search_filters` dependency: importing the `search` package is NOT import-light, because its package init imports the searcher orchestration class, which transitively pulls the store and embeddings. The validation leaf module, by contrast, imports only the standard-library typing module. So the transport imports the validator directly from the leaf module, not the package. This was verified empirically: after the lazy package init landed, importing the validation leaf module pulls none of the heavy modules, and importing the assembled service-client package is confirmed clean.
