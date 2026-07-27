---
tags:
  - '#plan'
  - '#mcp-project-root-contract'
date: '2026-07-25'
modified: '2026-07-27'
tier: L1
related:
  - '[[2026-07-25-mcp-project-root-contract-adr]]'
  - '[[2026-07-25-mcp-project-root-contract-research]]'
---
# `mcp-project-root-contract` plan

## Description

No separate description is recorded in the retained prior plan body. Source: retained prior plan body.

## Steps

- [x] `S01` - Add a single dispatch-root seam on the MCP adapter and forward every delegation site through it; `src/vaultspec_rag/mcp/_tools.py`.
- [x] `S02` - Route the vault document resource through the same seam, since a resource URI carries no root; `src/vaultspec_rag/mcp/_resources.py`.
- [ ] `S03` - Assert against a recording daemon that an omitting caller sends a concrete root and an explicit root still wins; `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`.

## Parallelization

No separate parallelization is recorded in the retained prior plan body. Source: retained prior plan body.

## Verification

No separate verification is recorded in the retained prior plan body. Source: retained prior plan body.
