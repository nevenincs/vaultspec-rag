---
tags:
  - '#adr'
  - '#mcp-server-deconflation'
date: '2026-06-07'
related:
  - "[[2026-06-07-mcp-server-deconflation-research]]"
---

# `mcp-server-deconflation` adr: `MCP and Server Deconflation` | (**status:** `accepted`)

## Problem Statement

The project uses the term `mcp_server` (and `mcp` in CLI flags) to describe the general, background HTTP REST service/daemon. The daemon handles background indexing tasks, file watching, and REST routes, which are independent of the Model Context Protocol (MCP). This conflation leads to severe cognitive load, misleading docstrings, and a heavily nested CLI structure. It also prevents us from safely optimizing the general search engine, as changes are conceptually coupled to the MCP protocol adapter.

## Considerations

- The REST RAG service must exist independently to manage local background jobs and provide an endpoint for indexing coordination.
- The MCP server should be a lightweight protocol adapter (stdio or SSE) that translates LLM requests into calls to either the RAG service or the core `vaultspec_rag` API.
- Backwards compatibility must be maintained in the CLI output where feasible, but command grouping must be flattened to simplify user experience.

## Constraints

- Changing the Python package names will require updating all internal imports across the codebase.
- The `mcp.tool()` wrappers need to cleanly separate from the FastAPI server initialization logic.

## Implementation

1. **Package Separation**: Rename the `vaultspec_rag/mcp_server` subpackage.
   - Core REST, job management, watcher, and global lifespans will move to `vaultspec_rag/server`.
   - The MCP protocol adapter and `@mcp.tool()` definitions will remain in a dedicated `vaultspec_rag/mcp` subpackage.
1. **CLI Redesign**: Restructure `vaultspec_rag/cli/_app.py`.
   - Collapse `vaultspec-rag server service <cmd>` into `vaultspec-rag server <cmd>`.
   - Maintain or shift `vaultspec-rag server mcp` to simply `vaultspec-rag mcp`.
1. **Documentation Audit**: Sweep all docstrings in `_index.py`, `_process.py`, and `_service_lifecycle.py` to correctly reference the "RAG Service" or "RAG Daemon" instead of the MCP Server.

## Rationale

Establishing a clean boundary between the core daemon and the protocol adapter aligns with proper software architecture principles. Decoupling the general HTTP daemon from MCP serialization ensures that background capabilities can scale and be optimized without violating the protocol wrapper contracts.

## Consequences

- **Gains:** Crystal-clear module boundaries, significantly simplified CLI commands, and correct, non-misleading documentation.
- **Difficulties:** A massive cross-file refactor of imports is necessary, which carries a risk of breaking internal wiring if not tested comprehensively. This includes renaming and updating the test suite (`tests/test_mcp_server.py`) and correcting framework rule documentation (`.vaultspec/rules/vaultspec-rag.builtin.md`).

## Codification candidates

- **Rule slug:** `mcp-is-not-the-daemon`.
  **Rule:** The term "MCP Server" must strictly refer to the stdio/SSE protocol serialization layer; all general background processes, watchers, and indexing REST services must be referred to as the "RAG Server" or "RAG Service" to prevent terminological conflation.
