---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-09'
step_id: 'P06.S21'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P06.S21 - fix CLI user-facing daemon strings

scope: `src/vaultspec_rag/cli/_search.py`, `_index.py`, `_store.py`,
`_service_lifecycle.py`, `_process.py`, `_render.py`

## Description

Reworded every user-facing string where "MCP server" actually meant the background HTTP
RAG daemon, and switched the transport-path marker accordingly:

- `--port` help text: "Port of running MCP server (fast path)." → "Port of running RAG
  service (fast path)." (`_search.py`, `_index.py`).
- Command docstrings "delegates to a running MCP server" → "RAG service" (`_search.py`,
  `_index.py`).
- Lock-holder candidate lists ("...command, MCP server, HTTP service...") reworded to name
  the RAG service (`_search.py`, `_store.py`).
- `_service_lifecycle.py`: "Spawns the MCP server on the given port" → "Spawns the RAG
  service".
- `_process.py`: `_spawn_service` docstring "Spawn the MCP server" → "Spawn the RAG
  service".
- JSON payload marker `"via": "mcp"` → `"via": "service"` (`_search.py`, `_index.py`);
  `_render.py` default `command`/error kwargs and the `via` docstring example updated to
  match.

## Outcome

`grep -ri "mcp server" src/vaultspec_rag/cli/` now matches only `cli/_mcp_admin.py` (the
genuine MCP-adapter control surface). The `P06.S23` guard enforces this. `ruff`/`ty` clean.

## Notes

Post-deconflation the MCP adapter is a pure REST client that holds no Qdrant lock and is
never a `--port` target, so naming it as a lock holder / port target was factually wrong,
not merely stylistic.
