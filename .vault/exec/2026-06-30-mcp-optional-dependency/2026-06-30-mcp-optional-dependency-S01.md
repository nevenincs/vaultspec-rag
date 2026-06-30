---
tags:
  - '#exec'
  - '#mcp-optional-dependency'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-30-mcp-optional-dependency-plan]]"
---

# Move mcp from project.dependencies to the project.optional-dependencies mcp extra

## Scope

- `pyproject.toml`

## Description

Moved mcp out of core dependencies into the [mcp] extra.

## Outcome

`mcp>=1.26.0` removed from `[project.dependencies]` and `[project.optional-dependencies].mcp` set to `["mcp>=1.26.0"]` (was a no-op alias). A base `pip install vaultspec-rag` now installs no mcp and no pywin32; `vaultspec-rag[mcp]` installs it. uv.lock re-resolved (MO1).

## Notes

Verified in the lock: mcp absent from vaultspec-rag base dependencies, present in the optional-dependencies mcp extra.
