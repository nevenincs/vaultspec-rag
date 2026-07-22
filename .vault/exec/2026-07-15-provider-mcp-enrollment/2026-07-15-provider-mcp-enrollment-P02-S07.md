---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S07'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Make --mcp and --no-mcp reconcile only the canonical MCP source while retaining the rule and discovery skill

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/tests/test_install_mcp_extra.py`
- `src/vaultspec_rag/tests/test_install_mode.py`

## Description

- Reconcile the optional extra through the placement-aware TOML engine without shelling out.
- Keep or remove only the canonical MCP source according to `--mcp/--no-mcp`.
- Retain the bundled rule and discovery skill in both states.
- Update real install tests to exercise enabled and disabled intent without network access.

## Outcome

Install now treats MCP intent as two symmetric axes: source enrollment and dependency
placement. Tool mode uses the extra-aware `uvx` source without mutating the project;
dependency and dev modes update their existing requirement surface; `--no-mcp` removes
the canonical source and reverses only an owned extra.

## Notes

Ruff, BasedPyright, Ty, complexity gates, and 38 real install/mode tests pass. Provider
entry pruning is deliberately left to the Core-backed project sync in Step S03.
