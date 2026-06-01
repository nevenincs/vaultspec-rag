---
tags:
  - '#plan'
  - '#module-split'
date: '2026-06-01'
tier: L2
related:
  - '[[2026-06-01-module-split-adr]]'
  - '[[2026-06-01-module-split-audit]]'
  - '[[2026-06-01-module-split-research]]'
---

# `module-split` `split monolithic modules into packages` plan

## Description

This plan splits the monolithic modules identified in the module-split audit
into packages, each preserving its verbatim public surface per the module-split
ADR. One phase per module, ordered low-risk to high-risk (commands,
torch_config, search, indexer, cli, mcp_server). `store.py` is intentionally
excluded (kept single-file).

## Steps

Each phase splits one module into a `module/` package whose `__init__.py`
re-exports the exact prior surface, then gates on the full relevant test suite
plus ruff, ruff-format, and ty passing unedited.

### Phase `P01` - split commands.py (validate pattern)

Split commands.py into a commands/ package re-exporting the verbatim public surface; lowest-risk first to validate the pattern.

- [x] `P01.S01` - Split into a package re-exporting the verbatim public surface, then verify full suite + ruff + ty green; `src/vaultspec_rag/commands.py`.

### Phase `P02` - split torch_config.py

Split torch_config.py into a package; pure functions, no module state.

- [x] `P02.S02` - Split into a package re-exporting the verbatim public surface, then verify full suite + ruff + ty green; `src/vaultspec_rag/torch_config.py`.

### Phase `P03` - split search.py

Split search.py into a package; VaultSearcher plus orthogonal pure helpers.

- [x] `P03.S03` - Split into a package re-exporting the verbatim public surface, then verify full suite + ruff + ty green; `src/vaultspec_rag/search.py`.

### Phase `P04` - split indexer.py

Split indexer.py into a package; VaultIndexer/CodebaseIndexer with shared AST constants.

- [ ] `P04.S04` - Split into a package re-exporting the verbatim public surface, then verify full suite + ruff + ty green; `src/vaultspec_rag/indexer.py`.

### Phase `P05` - split cli.py

Split the cli.py monolith into a package; preserve Typer app nesting and 24 external symbols.

- [ ] `P05.S05` - Split into a package preserving Typer app nesting and all external symbols, then verify full suite + ruff + ty green; `src/vaultspec_rag/cli.py`.

### Phase `P06` - split mcp_server.py

Split mcp_server.py into a package; preserve the FastMCP mcp global, tool registration, and the :main entry point.

- [ ] `P06.S06` - Split into a package preserving the FastMCP mcp global, tool registration, and the main entry point, then verify full suite + ruff + ty green; `src/vaultspec_rag/mcp_server.py`.

## Parallelization

Phases are strictly sequential: each split lands only when the full suite is
green, so a later split never builds on an unverified earlier one. Order is
risk-ascending (P01 commands through P06 mcp_server) to validate the re-export
pattern on simple modules before the FastMCP/entry-point module.

## Verification

The plan is complete when every module phase is closed. Each phase's gate: the
package re-exports the verbatim pre-split surface (no test edits), the full
relevant test suite passes, and ruff, ruff-format, and ty are clean. `store.py`
remains a single file.
