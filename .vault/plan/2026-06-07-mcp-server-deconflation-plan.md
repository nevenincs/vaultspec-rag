---
tags:
  - '#plan'
  - '#mcp-server-deconflation'
date: '2026-06-07'
tier: L2
related:
  - '[[2026-06-07-mcp-server-deconflation-adr]]'
  - '[[2026-06-07-mcp-server-deconflation-research]]'
---

# `mcp-server-deconflation` `MCP and Server Deconflation` plan

## Description

This plan implements the structural and terminological deconflation of the RAG Service and the MCP Server (Issues #167, #168, #169) as codified in `[[2026-06-07-mcp-server-deconflation-adr]]`. The `vaultspec_rag/mcp_server` package is currently overloaded with general background daemon logic (FastAPI, job queues, Qdrant orchestration) alongside the MCP protocol layer. We will extract the MCP layer to a dedicated `mcp` subpackage, rename the rest to `server`, and flatten the CLI hierarchy from `server service` to `server`.

## Steps

### Phase `P01` - Package Deconflation

Rename mcp_server to server and isolate mcp protocol adapter

- [ ] `P01.S01` - Rename vaultspec_rag/mcp_server to vaultspec_rag/server; `src/vaultspec_rag/server`.
- [ ] `P01.S02` - Extract MCP protocol layer to vaultspec_rag/mcp; `src/vaultspec_rag/mcp`.
- [ ] `P01.S05` - Rename test_mcp_server.py to test_server.py and update test imports; `tests/test_mcp_server.py`.
- [ ] `P01.S06` - Update mcp_server references in CLI and daemon tests; `tests/`.

### Phase `P02` - CLI and Docs Redesign

Flatten the CLI command hierarchy and audit docstrings

- [ ] `P02.S03` - Flatten server service to server; `src/vaultspec_rag/cli/_app.py`.
- [ ] `P02.S04` - Audit docstrings and help text; `src/vaultspec_rag/cli`.
- [ ] `P02.S07` - Update mcp_server entrypoint in framework rules and sync; `.vaultspec/rules/`.

## Parallelization

Phases MUST be executed sequentially. `P01` must fully land so the new package structure exists before `P02` updates the CLI to point to it.

## Verification

The plan is complete when:

1. `vaultspec-rag server start` successfully launches the general daemon, and `vaultspec-rag mcp` launches the MCP tool server.
1. The `pytest` test suite passes.
1. A `grep -ir 'mcp_server'` yields no results outside of the `mcp/` directory.
