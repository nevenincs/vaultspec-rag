---
tags:
  - '#plan'
  - '#mcp-launch-hygiene'
date: '2026-07-17'
modified: '2026-07-27'
tier: L1
related:
  - '[[2026-07-17-mcp-launch-hygiene-adr]]'
  - '[[2026-07-17-mcp-launch-hygiene-research]]'
---

# `mcp-launch-hygiene` plan

## Description

No separate description is recorded in the retained prior plan body. Source: retained prior plan body.

## Steps

- [x] `S01` - Add the \_vaultspec_mode_tool_spec token (vaultspec-rag[mcp]) to the builtin MCP seed and regenerate the committed workspace mirror through the seeder; `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json`.
- [x] `S02` - Make the ensure-mcp-extra step placement-aware: detect rag's existing declaration in the host pyproject, fall back to the declared mode, skip in tool mode, and thread the resolved placement from the install orchestrator; `src/vaultspec_rag/commands/_uv_sync.py`.
- [x] `S03` - Pin the contract with tests: placement matrix for the extra step and the stale-exe-seed refresh on install --upgrade; `src/vaultspec_rag/tests/test_install_mcp_extra.py`.
- [x] `S04` - Document the pre-parity workspace remediation (install --upgrade seed refresh) in the installation guide; `docs/installation.md`.

## Parallelization

No separate parallelization is recorded in the retained prior plan body. Source: retained prior plan body.

## Verification

No separate verification is recorded in the retained prior plan body. Source: retained prior plan body.
