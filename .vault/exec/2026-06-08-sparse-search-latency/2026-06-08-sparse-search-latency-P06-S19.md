---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
step_id: 'P06.S19'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P06.S19 - server docstring deconflation

scope: `src/vaultspec_rag/server/__init__.py`, `src/vaultspec_rag/server/_main.py`, `src/vaultspec_rag/server/_models.py`, `src/vaultspec_rag/server/_state.py`

## Description

- Rewrote `server/__init__.py` module docstring: "MCP server for VaultSpec RAG search and retrieval." → "RAG daemon HTTP service for VaultSpec RAG search and retrieval."; replaced "the server runs" → "the daemon runs" in the same paragraph.
- Rewrote `server/_main.py` module docstring: "Console-script entry point for the MCP server." → "...for the RAG daemon."
- Rewrote `server/_main.py` function docstring: "Start the MCP server on stdio or HTTP transport." → "Start the RAG daemon on stdio or HTTP transport."
- Rewrote `server/_main.py` argparse `description=`: "VaultSpec RAG MCP server" → "VaultSpec RAG daemon".
- Rewrote `server/_models.py` module docstring: "Pydantic response models for the MCP server." → "...for the RAG daemon."
- Rewrote `server/_state.py` module docstring first line: "Shared module-level state for the MCP server package." → "...for the RAG daemon (server) package."

## Outcome

All six docstring/comment targets corrected. `ruff check` passes clean on all four files. No code behavior, identifiers, or logic changed.

## Notes

Strings accurately describing the genuine MCP stdio/SSE transport layer were left unchanged:

- `server/_main.py` line: `mcp.run(transport="stdio")` — correct reference to the MCP protocol.
- `server/_main.py` comment: `# Eager model load for stdio - matches HTTP mode's service_lifespan.` — describes transport mode, not the daemon identity.
- `server/__init__.py` body: `alongside the MCP transport at /mcp` — accurately names the protocol endpoint, not the daemon.
- `server/_main.py` function body: `Mount("/mcp", mcp.streamable_http_app())` — code identifier, not a docstring claim.
- `server/_models.py` body: `across the MCP transport` — accurately describes the wire protocol used for serialization.
