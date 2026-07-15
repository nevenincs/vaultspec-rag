---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S09'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Add real-behavior mode and enrollment tests for both provider-native targets

## Scope

- `src/vaultspec_rag/tests/test_install_mode.py`
- `src/vaultspec_rag/tests/test_cli.py`
- `src/vaultspec_rag/commands/_models.py`
- `src/vaultspec_rag/commands/_install.py`
- `and src/vaultspec_rag/commands/_uninstall.py`

## Description

- Exercise tool, dependency, and dev launches in Claude-only, Codex-only, and
  dual-provider workspaces.
- Prove dual-provider reinstall leaves both native configs and ownership state
  byte-identical.
- Drift each provider independently and prove forced repair leaves the correct
  sibling target untouched.
- Isolate MCP lifecycle results from ordinary resource `per_tool` results before
  report aggregation.

## Outcome

All nine provider/mode combinations render the canonical RAG launch into exactly the
enrolled host targets. Reinstall is byte-stable in every mode, and forced repair updates
only the drifted Claude or Codex target. Reports now aggregate only explicitly recorded
MCP lifecycle results, so rule, skill, and agent sync counts cannot be mislabeled as MCP
outcomes.

## Notes

The first parity run exposed that ordinary Core resource results also use `per_tool`.
The open Step scope was expanded through the plan CLI and the report model now carries a
dedicated `mcp_sync_results` channel populated by install, migration, and uninstall.
Forty-six focused tests pass with Ruff, formatting, BasedPyright, Ty, and the full
complexity gate against Core `e81569e3`.
