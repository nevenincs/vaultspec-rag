---
tags:
  - '#plan'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
tier: L2
related:
  - '[[2026-06-05-cli-mcp-decoupling-adr]]'
  - '[[2026-06-05-cli-mcp-decoupling-research]]'
---

# `cli-mcp-decoupling` `interface layers` plan

### Phase `P01` - Decouple CLI commands and move logic to backend

Decouple benchmark, quality, and testing orchestration from the CLI into the core backend facade API.

- [x] `P01.S01` - Extract latency benchmark logic from CLI into new backend API function run_benchmark; `src/vaultspec_rag/api.py`.
- [x] `P01.S02` - Refactor CLI benchmark command to call run_benchmark and render the table; `src/vaultspec_rag/cli/_benchmark.py`.
- [x] `P01.S03` - Extract synthetic quality testing logic from CLI into new backend API function run_quality_probe; `src/vaultspec_rag/api.py`.
- [x] `P01.S04` - Refactor CLI quality command to call run_quality_probe and print the results; `src/vaultspec_rag/cli/_quality.py`.

### Phase `P02` - Refactor MCP Server Tools and Parity

Ensure the MCP server admin tools delegate to unified backend APIs, and expose benchmark and quality tools to the MCP server.

- [x] `P02.S05` - Standardize get_service_state backend data collection into backend API; `src/vaultspec_rag/api.py`.
- [x] `P02.S06` - Add benchmark and quality tools to the MCP server by calling backend APIs; `src/vaultspec_rag/mcp_server/_admin_tools.py`.

### Phase `P03` - Integration Testing

Ensure all existing tests compile and run successfully against the new API structure.

- [x] `P03.S07` - Update existing integration tests to assert against the backend API; `src/vaultspec_rag/tests/test_cli.py`.

## Description

This plan refactors the CLI and MCP interface layers of `vaultspec-rag` to completely decouple them from core business logic. All orchestration of benchmarks, synthetic quality tests, and service-state diagnostics is moved to the core `vaultspec_rag` backend facade in `src/vaultspec_rag/api.py`.

## Steps

All phases and steps are declared above in accordance with the L2 plan structure.

## Parallelization

Phases `P01` (CLI refactoring) and `P02` (MCP refactoring) can be executed in parallel as they modify separate client surfaces. Phase `P03` (Integration Testing) must run after both `P01` and `P02` are complete.

## Verification

- Running `just dev test python` (or `pytest`) executes all integration tests successfully.
- Direct CLI invocations (`benchmark`, `quality`) run correctly and output tables and JSON envelopes.
- MCP tool calls (`benchmark`, `quality`) return valid JSON-RPC payloads.
- Pre-commit hooks run cleanly with zero lint or type check failures.
