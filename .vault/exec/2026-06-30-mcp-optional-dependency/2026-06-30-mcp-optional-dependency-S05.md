---
tags:
  - '#exec'
  - '#mcp-optional-dependency'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S05'
related:
  - "[[2026-06-30-mcp-optional-dependency-plan]]"
---

# Make vaultspec-rag install ensure the [mcp] extra by default with a --mcp/--no-mcp opt-out mirroring core

## Scope

- `src/vaultspec_rag/cli/_install.py`

## Description

Made `vaultspec-rag install` ensure the optional `[mcp]` extra by default, with a `--mcp/--no-mcp` opt-out.

## Outcome

Added the `--mcp/--no-mcp` flag (default on) mirroring `--torch-config/--no-torch-config` and `--provision/--no-provision`. When on, install shells out to `uv add vaultspec-rag[mcp]` (via `_run_uv_add_mcp_extra`, non-fatal, classified into `report.mcp_extra_action`) so the agent-facing MCP server it just wired up has its dependency. `install_run` defaults `install_mcp=False` (the on-by-default polarity lives at the CLI edge) so programmatic callers and network-free tests never shell out, mirroring `provision`.

## Notes

Tests: classifier branches, dry-run would-add vs --no-mcp skipped, orchestrator-default-off, CLI flag default on. The guard message and docs now say `uv add vaultspec-rag[mcp]` (not pip).
