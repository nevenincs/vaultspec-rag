---
tags:
  - "#exec"
  - "#mcp-server-deconflation"
date: 2026-06-08
modified: '2026-06-30'
related:
  - "[[2026-06-07-mcp-server-deconflation-plan]]"
---

# mcp-server-deconflation P02 S11

## Intent

Update `mcp_server` entrypoint in framework rules and sync; `.vaultspec/rules/`.

## Context

The legacy module `vaultspec_rag.mcp_server` was refactored. The MCP transport logic is now housed in `vaultspec_rag.mcp:main` (used for the `vaultspec-search-mcp` CLI entrypoint), while the REST service is now purely `vaultspec_rag.server`. The framework documentation `.vaultspec/rules/rules/vaultspec-rag.builtin.md` still contained references to `mcp_server:main`.

## Action

- Updated `.vaultspec/rules/rules/vaultspec-rag.builtin.md` to reference `vaultspec_rag.mcp:main` instead of `vaultspec_rag.mcp_server:main`.
- Verified that `vaultspec-rag.builtin.json` MCP config properly delegates to `vaultspec-search-mcp` entrypoint (which was already mapped to `vaultspec_rag.mcp:main` in `pyproject.toml`).
- Ran `vaultspec-core sync` (via tests implicitly and verified rules sync).

## Outcome

All documentation accurately reflects the module deconflation. The MCP adapter properly uses the standard entrypoint mapping.
