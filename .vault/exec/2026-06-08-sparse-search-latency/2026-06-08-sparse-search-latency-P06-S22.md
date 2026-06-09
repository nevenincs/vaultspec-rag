---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
step_id: 'P06.S22'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P06.S22 - registry/service stale module reference fix

scope: `src/vaultspec_rag/registry.py`, `src/vaultspec_rag/service.py`

## Description

- Rewrote `registry.py` module docstring: reference to deleted `mcp_server.py` → `server/_main.py` ("both `api.py` and `mcp_server.py` tried to import..." → "both `api.py` and `server/_main.py` tried to import...").
- Rewrote `service.py` module docstring: reference to deleted `mcp_server.py` → the RAG daemon (`server/_main.py`) ("initialization in `api.py` and `mcp_server.py`" → "initialization in `api.py` and the RAG daemon (`server/_main.py`)").

## Outcome

Both stale `mcp_server.py` references eliminated. `ruff check` passes clean on both files. No code behavior, identifiers, or logic changed.

## Notes

No strings were left as "MCP" in these files; the only "MCP"-adjacent text was the deleted module filename `mcp_server.py`, which no longer exists.
