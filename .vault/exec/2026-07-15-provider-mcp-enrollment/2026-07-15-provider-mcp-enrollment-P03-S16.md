---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S16'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Fail closed on top-level and per-provider MCP lifecycle errors with complete reports and CLI regressions

## Scope

- `src/vaultspec_rag/commands/_models.py`
- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/commands/_uninstall.py`
- `src/vaultspec_rag/cli/_install.py`
- `src/vaultspec_rag/cli/_render.py`
- `and tests`

## Description

- Preserve direct lifecycle exceptions and unattributed top-level Core errors in structured reports.
- Keep per-provider counters, warnings, and errors separate while deriving one fail-closed status.
- Render top-level and provider-attributed failures in human output and expose both in JSON.
- Make install and uninstall exit two whenever a requested MCP lifecycle operation fails.
- Add real malformed-Codex and corrupt-ownership API and CLI regressions.

## Outcome

Provider-attributed errors and ownership-sidecar errors now remain visible without
duplication, and `mcp_failed` gives API consumers a single honest result. Install and
uninstall emit their complete report before exiting two. Six focused report tests,
three real failure-path acceptance tests, the 62-test MCP-focused slice, Ruff, Ty, and
BasedPyright pass.

## Notes

Core merges per-provider errors into its top-level accumulator. The report removes
already-attributed messages from the unattributed list while still treating either
level as a failure.
