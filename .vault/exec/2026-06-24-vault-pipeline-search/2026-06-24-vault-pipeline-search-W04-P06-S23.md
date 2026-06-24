---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S23'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Mirror the new params on the MCP search_vault tool for adapter parity

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

- Added an explicit `intent` parameter to the MCP `search_vault` tool, forwarded to the
  shared `_try_http_search` transport so the MCP adapter selects the same ranking profile.
- Documented in the tool docstring that `doc_type` accepts a comma-separated union, that the
  inline `intent:`/`status:`/`type:` tokens are equivalent, and that results carry status and
  related edges.

## Outcome

The MCP adapter now has parity with the CLI and HTTP route: intent via the explicit param,
doc-type union via the comma-list `doc_type`, and status via the inline `status:` token, all
flowing through the one shared transport and service contract. `ruff` and `ty` pass.

## Notes

MCP tool functions are well under the max-args ratchet, so intent is an explicit param here
(unlike the CLI, which uses the inline token). No blockers.
