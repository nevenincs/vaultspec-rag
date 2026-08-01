---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:2d9e0d57ede8feb01123999299c373d426e52455a04afd73a3d53cfd1aca8e90'
step_id: 'S27'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Make implicit MCP skips status-free and migrate owned dependency-extra placement

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/commands/_mode.py`
- `src/vaultspec_rag/commands/_mcp_extra.py`
- `and real placement regressions`

## Description

- Resolve implicit skipped upgrades from durable declaration and package placement only.
- Move exact owned MCP-extra edits between runtime and development target surfaces.
- Preserve old unowned base declarations and release provenance when the target extra is unowned.
- Cover malformed provider and ownership state, both skip combinations, round trips, conflicts, and uninstall.

## Outcome

MCP- and Core-skipped implicit upgrades no longer inspect native status. Malformed Codex
and ownership state cannot force tool mode or remove an owned runtime extra. Managed
dependency-to-dev and dev-to-dependency transitions restore the exact old owned edit,
apply the extra at the requested surface, update ownership, preview without writes,
round-trip byte-exactly, and uninstall back to the original declaration.

## Notes

Four real implicit-skip corruption combinations, two real placement transitions, three
focused ownership moves, and the neighboring mode, partial-provider, and explicit-skip
matrices passed. Unowned target extras remain byte-preserved and are not adopted.
