---
tags:
  - "#adr"
  - "#mcp-server-deconflation"
date: '2026-06-07'
related:
  - "[[2026-06-07-mcp-server-deconflation-research]]"
superseded_by: '2026-06-18-mcp-service-client-adr'
modified: '2026-06-30'
---

# `mcp-server-deconflation` adr: `MCP and Server Deconflation` | (**status:** `superseded`)

## Problem Statement

The project uses the term `mcp_server` (and `mcp` in CLI flags) to describe the general, background HTTP REST service/daemon. The daemon handles background indexing tasks, file watching, and HTTP routes, but does so while exposing an MCP HTTP SSE endpoint as its primary interaction model. This architectural and terminological conflation prevents the general RAG server from having its own identity and native REST API. Because the daemon is treated as an MCP server, both the CLI and the MCP protocol wrapper remain entangled with the daemon's lifecycle, rather than acting as pure consumer clients of a standalone RAG service.

## Considerations

- The REST RAG service must exist independently to manage local background jobs and provide native REST endpoints for indexing coordination and search operations.
- The MCP and CLI are **consumer clients** of the server service; therefore, they must decouple from the backend. The MCP server should be a lightweight protocol adapter (stdio or SSE) that simply makes requests to the RAG service REST API.
- All refactoring must be a hard, clean cut. There will be absolutely no backwards or legacy support, shims, shadows, stubs, mirrors, or dead code kept to support old CLI paths or module imports.

## Constraints

- Changing the Python package names will require updating all internal imports across the codebase; any old paths must be entirely removed, not stubbed or forwarded.
- The daemon must implement its own REST API (`/search`, `/reindex`) to replace the MCP HTTP SSE endpoint it currently uses to communicate with the CLI.

## Implementation

1. **Package and Architectural Separation**: Rename the `vaultspec_rag/mcp_server` subpackage.
   - Core HTTP, job management, watcher, and global lifespans will move to `vaultspec_rag/server`.
   - The daemon must expose native REST endpoints (`/search`, `/reindex`) instead of solely acting as an MCP SSE host.
   - The MCP protocol adapter and `@mcp.tool()` definitions will move to a dedicated `vaultspec_rag/mcp` subpackage, and will be refactored to act as a consumer client rather than executing RAG in-process.
1. **CLI Redesign**: Restructure `vaultspec_rag/cli/_app.py` and `_mcp_search.py`.
   - Collapse `vaultspec-rag server service <cmd>` into `vaultspec-rag server <cmd>`.
   - Move the MCP stdio wrapper startup to `vaultspec-rag mcp`.
   - Update the CLI `_try_mcp_search` path to instead consume the new REST API (`_try_http_search`) when delegating to the daemon.
1. **Documentation Audit**: Sweep all docstrings in `_index.py`, `_process.py`, and `_service_lifecycle.py` to correctly reference the "RAG Service" or "RAG Daemon" instead of the MCP Server.

## Rationale

Establishing a clean boundary between the core daemon and the protocol adapter aligns with proper software architecture principles. Decoupling the general HTTP daemon from MCP serialization ensures that the server can expose standard REST APIs, and allows the MCP stdio wrapper and the CLI to act as true consumer clients of the service.

## Consequences

- **Gains:** Crystal-clear module boundaries, significantly simplified CLI commands, native REST endpoints for the daemon, and correct, non-misleading documentation.
- **Difficulties:** A massive cross-file refactor of imports is necessary. The CLI fast-path must be rewritten to consume REST instead of MCP. The test suite (`tests/test_mcp_server.py`) and framework rules (`.vaultspec/rules/vaultspec-rag.builtin.md`) must be thoroughly updated.

## Codification candidates

- **Rule slug:** `mcp-is-not-the-daemon`.
  **Rule:** The term "MCP Server" must strictly refer to the stdio/SSE protocol serialization layer; all general background processes, watchers, and indexing REST services must be referred to as the "RAG Server" or "RAG Service" to prevent terminological conflation. The MCP adapter and CLI must always act as consumer clients.
