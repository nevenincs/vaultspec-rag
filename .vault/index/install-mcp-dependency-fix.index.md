---
generated: true
tags:
  - '#index'
  - '#install-mcp-dependency-fix'
date: '2026-06-10'
related:
  - '[[2026-06-10-install-mcp-dependency-fix-S01]]'
  - '[[2026-06-10-install-mcp-dependency-fix-S02]]'
  - '[[2026-06-10-install-mcp-dependency-fix-S03]]'
  - '[[2026-06-10-install-mcp-dependency-fix-S04]]'
  - '[[2026-06-10-install-mcp-dependency-fix-adr]]'
  - '[[2026-06-10-install-mcp-dependency-fix-plan]]'
  - '[[2026-06-10-install-mcp-dependency-fix-research]]'
---

# `install-mcp-dependency-fix` feature index

Auto-generated index of all documents tagged with `#install-mcp-dependency-fix`.

## Documents

### adr

- `2026-06-10-install-mcp-dependency-fix-adr` - `install-mcp-dependency-fix` adr: `declare mcp as a core dependency; reject pywin32 dll shim` | (**status:** `accepted`)

### exec

- `2026-06-10-install-mcp-dependency-fix-S01` - Promote mcp to core dependencies, collapse the mcp extra to a deprecated no-op alias kept for backward-compat, and drop the duplicate mcp from the dev extra and dev dependency-group
- `2026-06-10-install-mcp-dependency-fix-S02` - Guard the unconditional mcp import in main with try/except re-raising a chained RuntimeError carrying an actionable uv and pywin32 remediation message, messaging only with no DLL handling
- `2026-06-10-install-mcp-dependency-fix-S03` - Add a packaging-metadata regression test asserting importlib.metadata.requires reports mcp as a core requirement with no extra marker
- `2026-06-10-install-mcp-dependency-fix-S04` - Run uv sync, ruff, basedpyright and the unit suite, verify the server entry import path is clean, file the upstream mcp 2233 version-floor follow-up issue, then commit

### plan

- `2026-06-10-install-mcp-dependency-fix-plan` - `install-mcp-dependency-fix` `declare mcp core dependency and guard server import` plan

### research

- `2026-06-10-install-mcp-dependency-fix-research` - `install-mcp-dependency-fix` research: `issue 182 mcp dependency and pywin32 ownership`
