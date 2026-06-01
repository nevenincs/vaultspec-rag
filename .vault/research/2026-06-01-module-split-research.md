---
tags:
  - '#research'
  - '#module-split'
date: '2026-06-01'
related: []
---

# module-split research: package + `__init__` re-export pattern

How to break the oversized modules (`cli.py`, `indexer.py`, `mcp_server.py`,
`torch_config.py`, `search.py`, `commands.py`) into manageable chunks without
breaking any caller or test. Structural analysis mapped each module's logical
sections and, critically, its complete external import surface (the symbols
other modules and tests import from it). The detailed inventory and per-module
verdicts live in the module-split audit; this records the chosen pattern.

## Findings

- **Pattern: module -> package with re-exporting `__init__`.** Turn `module.py`
  into a package `module/`, move cohesive sections into `_`-prefixed submodules,
  and have `module/__init__.py` re-export the verbatim pre-split public surface
  via an explicit `__all__`. Callers keep doing
  `from vaultspec_rag.module import X` unchanged.
- **The surface includes `_`-prefixed helpers.** Tests import many private
  helpers directly (e.g. `cli._spawn_service`, `mcp_server._ensure_watcher`,
  `commands._classify_uv_sync_result`). These are de-facto public and must be
  re-exported, so tests pass unedited.
- **Shared module state stays in `__init__`.** For `mcp_server`, the
  module-level `mcp = FastMCP(...)` and the watcher/registry globals live in the
  package init, which imports the tool submodules so their `@mcp.tool()`
  decorators register against the one instance; the `:main` entry point stays
  importable from the package root.
- **No-public-surface-change is the safety gate.** Because imports do not move,
  the existing 640+ test suite is the regression net: a split lands only when
  the full suite plus ruff/ruff-format/ty pass without test edits.
- **`store.py` is kept whole** — one cohesive class with no architectural seam.
- **Verdict:** SPLIT `commands`, `torch_config`, `search`, `indexer`, `cli`,
  `mcp_server` (risk-ascending); KEEP `store` and all sub-threshold modules.
