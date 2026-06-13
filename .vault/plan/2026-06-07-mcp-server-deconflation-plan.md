---
tags:
  - '#plan'
  - '#mcp-server-deconflation'
date: '2026-06-07'
modified: '2026-06-07'
tier: L2
related:
  - '[[2026-06-07-mcp-server-deconflation-adr]]'
  - '[[2026-06-07-mcp-server-deconflation-research]]'
---

# `mcp-server-deconflation` `MCP and Server Deconflation` plan

## Description

This plan implements the structural and terminological deconflation of the RAG Service and the MCP Server (Issues #167, #168, #169) as codified in `[[2026-06-07-mcp-server-deconflation-adr]]`. The `vaultspec_rag/mcp_server` package is currently overloaded with general background daemon logic (FastAPI, job queues, Qdrant orchestration) alongside the MCP protocol layer, and it relies on an MCP SSE endpoint for IPC with the CLI. We will extract the MCP layer to a dedicated `mcp` subpackage, rename the rest to `server`, implement native REST endpoints for the daemon, and refactor both the CLI and MCP wrappers to act as pure consumer clients of the RAG service. This is a hard, clean cut: absolutely no backwards or legacy support, shims, shadows, stubs, mirrors, or dead code will be kept to support old CLI paths or module imports.

## Steps

### Phase `P01` - Package Deconflation and REST API Implementation

Rename mcp_server to server, implement REST endpoints, and isolate mcp protocol adapter

- [x] `P01.S01` - Rename vaultspec_rag/mcp_server to vaultspec_rag/server and update console script entrypoints; `src/vaultspec_rag/server`, `pyproject.toml`.
- [x] `P01.S02` - Extract MCP protocol layer to vaultspec_rag/mcp; `src/vaultspec_rag/mcp`.
- [x] `P01.S03` - Implement REST API endpoints (/search, /reindex) for the daemon; `src/vaultspec_rag/server/_routes.py`.
- [x] `P01.S04` - Rewrite MCP tools to strictly consume the REST API instead of in-process routing; `src/vaultspec_rag/mcp/_tools.py`.
- [x] `P01.S05` - Rewrite CLI delegation to use HTTP REST client instead of MCP client; `src/vaultspec_rag/cli/_mcp_search.py` -> `_http_search.py`.
- [x] `P01.S06` - Rename test_mcp_server.py to test_server.py and update test imports; `tests/test_mcp_server.py`.
- [x] `P01.S07` - Update mcp_server references in CLI and daemon tests; `tests/`.

### Phase `P02` - CLI and Docs Redesign

Flatten the CLI command hierarchy and audit docstrings

- [x] `P02.S09` - Flatten server service to server, and decouple mcp startup; `src/vaultspec_rag/cli/_app.py`, `_mcp_admin.py`.
- [x] `P02.S10` - Audit docstrings and help text; `src/vaultspec_rag/cli`.
- [x] `P02.S11` - Update mcp_server entrypoint in framework rules and sync; `.vaultspec/rules/`.

## Parallelization

Phases MUST be executed sequentially. `P01` must fully land so the new package structure exists before `P02` updates the CLI to point to it.

## Verification

The plan is complete when:

1. `vaultspec-rag server start` successfully launches the general daemon, and `vaultspec-rag mcp` launches the MCP tool server.
1. The `pytest` test suite passes.
1. A `grep -ir 'mcp_server'` yields no results outside of the `mcp/` directory.
1. The daemon correctly exposes native REST endpoints for indexing and searching.
