---
tags:
  - '#exec'
  - '#mcp-optional-dependency'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-30-mcp-optional-dependency-plan]]"
---

# Ensure the dev/test dependency set provides mcp so the test suite resolves

## Scope

- `pyproject.toml`

## Description

Added mcp to the dev dependency group so the test suite resolves.

## Outcome

`[dependency-groups].dev` now includes `mcp>=1.26.0`; `uv sync` installs it for development even though it is not a core dependency, so the mcp-importing tests keep resolving (MO2).

## Notes

132 mcp-dependent tests pass after the move.
