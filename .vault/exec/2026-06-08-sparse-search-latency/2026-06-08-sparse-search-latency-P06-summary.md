---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-09'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` Phase P06 Summary

## Overview

Phase P06 purges the semantic conflation where "MCP server" was used to mean the background
REST daemon, and where CLI identifiers used `mcp` to mean `service`. The genuine MCP stdio
protocol adapter (`mcp/` package and the `cli/_mcp_admin.py` control surface) keeps its
naming; everything that actually refers to the RAG daemon/service is renamed.

## Steps

- **S19**: server-package docstrings (`server/{__init__,_main,_models,_state}.py`) reworded
  from "MCP server" to "RAG daemon".
- **S20**: CLI identifiers `_handle_mcp_results`, `mcp_results`, `_display_mcp_error`,
  `_try_mcp_delegation`, `_print_mcp_results` renamed to their `service` equivalents; a
  leftover backward-compat alias was removed (hard clean cut) and `test_cli.py` updated.
- **S21**: user-facing daemon strings (help, docstrings, error messages, `"via"` marker)
  corrected across five CLI modules.
- **S22**: stale `mcp_server.py` module references in `registry.py` / `service.py`
  docstrings updated to `server/_main.py`.
- **S23**: added `test_no_mcp_server_conflation.py` guarding the terminological boundary,
  with documented exemptions for `mcp/` and `cli/_mcp_admin.py`.

## Outcome

No daemon-meaning "MCP server" wording remains outside the genuine MCP control surfaces
(grep- and test-verified). `ruff`/`ty` clean; 183 unit/guard tests and 11 admin/jobs
integration tests pass. The deconflation ADR's codification candidate `mcp-is-not-the-daemon`
is now enforced by the S23 guard.

## Notes

Executor work was delivered by four parallel Sonnet sub-agents over disjoint file sets; the
orchestrator handled cross-cutting cleanup (alias removal, `via` enum, `list_projects`
param) and final verification.
