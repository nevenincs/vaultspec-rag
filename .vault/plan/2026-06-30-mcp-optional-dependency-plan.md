---
tags:
  - '#plan'
  - '#mcp-optional-dependency'
date: '2026-06-30'
modified: '2026-06-30'
tier: L1
related:
  - '[[2026-06-30-mcp-optional-dependency-adr]]'
  - '[[2026-06-30-mcp-optional-dependency-research]]'
---

# `mcp-optional-dependency` plan

- [x] `S01` - Move mcp from project.dependencies to the project.optional-dependencies mcp extra; `pyproject.toml`.
- [x] `S02` - Ensure the dev/test dependency set provides mcp so the test suite resolves; `pyproject.toml`.
- [x] `S03` - Retarget the MCP-entry-point ImportError guard message at the vaultspec-rag[mcp] extra; `src/vaultspec_rag/server/_main.py`.
- [x] `S04` - Add a regression test asserting importing vaultspec_rag and the CLI loads no mcp or pywin32; `src/vaultspec_rag/tests/test_cli_no_mcp_import.py`.
- [x] `S05` - Make vaultspec-rag install ensure the [mcp] extra by default with a --mcp/--no-mcp opt-out mirroring core; `src/vaultspec_rag/cli/_install.py`.
## Description

## Steps

## Parallelization

## Verification
