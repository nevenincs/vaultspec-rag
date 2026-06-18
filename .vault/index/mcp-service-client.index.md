---
generated: true
tags:
  - '#index'
  - '#mcp-service-client'
date: '2026-06-18'
related:
  - '[[2026-06-18-mcp-service-client-P01-S01]]'
  - '[[2026-06-18-mcp-service-client-P01-S02]]'
  - '[[2026-06-18-mcp-service-client-P01-S03]]'
  - '[[2026-06-18-mcp-service-client-P01-S04]]'
  - '[[2026-06-18-mcp-service-client-P01-S05]]'
  - '[[2026-06-18-mcp-service-client-P01-S06]]'
  - '[[2026-06-18-mcp-service-client-P01-S07]]'
  - '[[2026-06-18-mcp-service-client-adr]]'
  - '[[2026-06-18-mcp-service-client-plan]]'
  - '[[2026-06-18-mcp-service-client-research]]'
---

# `mcp-service-client` feature index

Auto-generated index of all documents tagged with `#mcp-service-client`.

## Documents

### adr

- `2026-06-18-mcp-service-client-adr` - `mcp-service-client` adr: `MCP backend reframed as a thin service client` | (**status:** `accepted`)

### exec

- `2026-06-18-mcp-service-client-P01-S01` - Convert the top-level package init to lazy attribute loading so importing any submodule no longer eager-loads the heavy facade
- `2026-06-18-mcp-service-client-P01-S02` - Create the import-light service-client transport housing the HTTP call primitive and the search, reindex, and admin client functions
- `2026-06-18-mcp-service-client-P01-S03` - Create the import-light service-discovery module housing the status-file reader and default-port resolver
- `2026-06-18-mcp-service-client-P01-S04` - Add thin client wrappers for benchmark, quality, and code-file so the MCP inherits them without bespoke logic
- `2026-06-18-mcp-service-client-P01-S05` - Export the service-client public surface from the package init
- `2026-06-18-mcp-service-client-P01-S06` - Repoint the CLI HTTP search module to re-export from the service-client package, preserving the CLI surface
- `2026-06-18-mcp-service-client-P01-S07` - Repoint the CLI service-status discovery helpers to re-export from the service-client package

### plan

- `2026-06-18-mcp-service-client-plan` - `mcp-service-client` plan

### research

- `2026-06-18-mcp-service-client-research` - `mcp-service-client` research: `MCP backend rework as a thin service client`
