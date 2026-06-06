---
tags:
  - '#adr'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
related:
  - "[[2026-06-05-cli-mcp-decoupling-research]]"
---

# `cli-mcp-decoupling` adr: `decoupled interface layers and unified backend facade` | (**status:** `accepted`)

## Problem Statement

The CLI (`src/vaultspec_rag/cli/`) and MCP (`src/vaultspec_rag/mcp_server/`) entry points must act as thin transport wrappers. However, several CLI modules (such as `_benchmark.py` and `_quality.py`) currently implement their own benchmarking loops, test corpus generation, quality metric scoring, and system diagnostics. This violates the zero-business-logic interface mandate and introduces duplication.

## Considerations

- **Decoupled Interfaces**: Interface wrappers must only parse command arguments or payload parameters, forward them to the backend, and render the returned results.
- **Backend Facade**: All core capabilities—such as indexing, search, diagnostics, benchmarking, and quality checks—must reside in `vaultspec_rag` and be exposed through unified functions in `src/vaultspec_rag/api.py`.
- **Robust Integration Testing**: The A2A layer must be tested using real subprocesses and service calls to prevent gaps in transport/API verification.

## Constraints

- No circular dependencies can be introduced between the user-facing CLI/MCP modules and the core backend library.
- Standardized return types (such as custom TypedDicts or models) must be defined in the backend API to allow both CLI (Rich tables) and MCP (JSON-RPC) to format outputs from identical payloads.

## Implementation

- **API Facade Extensions**:
  - Implement `run_benchmark` in `src/vaultspec_rag/api.py` to orchestrate latency sweeps, calculate p50/p95/p99 percentiles, and return a dictionary of metrics.
  - Implement `run_quality_probes` in `src/vaultspec_rag/api.py` to create a synthetic corpus, run the indexer, execute semantic needle searches, and return score counts and pass/fail details.
- **CLI/MCP Interface Refactoring**:
  - Update `_benchmark.py` and `_quality.py` to call these new API functions and print tables or return JSON envelopes.
  - Audit MCP server admin tools to ensure `get_service_state` queries identical status payloads from the backend.

## Rationale

Decoupling all functional orchestration from CLI/MCP ensures that the backend remains completely agnostic. This guarantees behavior consistency across all clients, enables programmatic API usage, and makes the codebase easier to test.

## Consequences

- **Gains**:
  - Direct parity between CLI and MCP capabilities.
  - Thin, readable client wrappers focused entirely on formatting.
  - Standardized JSON and Rich table outputs generated from the same data source.
- **Pitfalls**:
  - Existing unit tests that mocked internal CLI methods must be updated to target the backend facade APIs.

## Codification candidates

- **Rule slug:** `interface-layer-zero-business-logic`.
  **Rule:** CLI and MCP modules must not contain custom business logic, loop orchestrations, or ML model configurations; they must delegate all operational tasks to the unified backend facade.
