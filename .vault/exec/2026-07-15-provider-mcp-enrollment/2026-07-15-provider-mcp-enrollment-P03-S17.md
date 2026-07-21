---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S17'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Remove dormant uv-add MCP code and stale prose and make the Core smoke floor future-compatible

## Scope

- `src/vaultspec_rag/commands/_uv_sync.py`
- `src/vaultspec_rag/tests/test_install_mcp_extra.py`
- `src/vaultspec_rag/cli/_install.py`
- `and tests/smoke_check.py`

## Description

- Remove the unreachable MCP uv-add subprocess helper, classifier, exports, and classifier tests.
- Rewrite install help, report comments, and MCP-extra test narrative around placement-aware reconciliation.
- Keep the exact published Core metadata floor while accepting any installed version that satisfies it.
- Exercise public Core status and selective-uninstall behavior in the installed-artifact smoke.

## Outcome

The source tree has one MCP-extra implementation and its tests now exercise that real
placement engine. The smoke accepts compatible future Core releases while retaining the
exact `>=0.1.44` metadata assertion and proving all three public lifecycle APIs through
real dual-provider enrollment, status, and uninstall preview. Twenty focused tests,
Ruff, formatting, and the complete source smoke pass.

## Notes

The server's manual `uv add vaultspec-rag[mcp]` recovery guidance remains intentional;
only the inaccurate claim that install shells out to that command was removed.
