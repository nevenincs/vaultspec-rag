---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:f417220ca97e21807fd2fef01b0a40fa279e7012c35d4b7b0e67f071424aaaf3'
step_id: 'S35'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Preserve every builtin destination across failed forced seed transitions

## Scope

- `src/vaultspec_rag/commands/_install.py and ordered real seed rollback tests`

## Description

- Extend the install transaction snapshot from the MCP source to every bundled
  MCP, rule, and skill destination.
- Restore overwritten operator bytes and remove only newly written builtins
  when a later ordered seed write fails.
- Exercise genuine final-skill atomic write blockers after earlier MCP and rule
  writes for both forced install and upgrade paths.
- Preserve pre-existing project and workspace lock bytes, blocker directories,
  and unrelated files under exact inventory comparison.

## Outcome

The ordered rollback matrix passes 10 tests and the complete install, mode,
torch, and native-host surface passes 195 tests. Ruff, formatting, Ty,
BasedPyright, complexity, lock consistency, and diff hygiene pass.

## Notes

S34 remains a durable failed audit recording the data-loss path that this step
closes. The complete selected repository aggregate restarts on the fresh S36
review target.
