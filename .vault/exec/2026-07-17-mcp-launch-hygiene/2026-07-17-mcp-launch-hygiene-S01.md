---
tags:
  - '#exec'
  - '#mcp-launch-hygiene'
date: '2026-07-17'
modified: '2026-07-17'
body_hash: 'sha256:74facad2a33047a93f5121d7e382230f53074b9b8de6bf6602b4d9c03501c2c1'
step_id: 'S01'
related:
  - "[[2026-07-17-mcp-launch-hygiene-plan]]"
---

# Add the \_vaultspec_mode_tool_spec token (vaultspec-rag[mcp]) to the builtin MCP seed and regenerate the committed workspace mirror through the seeder

## Scope

- `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json`

## Description

- Add `"_vaultspec_mode_tool_spec": "vaultspec-rag[mcp]"` to the builtin
  MCP seed so core's renderer produces `uvx --from "vaultspec-rag[mcp]" ...`
  in tool mode (the mcp optional extra otherwise never reaches a tool env).
- Regenerate the committed workspace mirror through `seed_builtins(force=True)`
  ([UPDATE] observed), never by hand.

## Outcome

Tool-mode renders now carry the mcp extra. Seeder round-trip verified.

## Notes

None.
