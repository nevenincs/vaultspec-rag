---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'P06.S20'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P06.S20 - rename CLI mcp\_\* identifiers to service\_\*

scope: `src/vaultspec_rag/cli/_search.py`, `_index.py`, `_render.py`, `__init__.py`

## Description

Renamed every conflated CLI identifier consistently across definitions, call sites,
imports, and `__all__` exports:

- `_handle_mcp_results` → `_handle_service_results` (`_search.py`)
- `mcp_results` (local) → `service_results` (`_search.py`)
- `_display_mcp_error` → `_display_service_error` (`_render.py`; imports in `_search.py`,
  `_index.py`, `__init__.py`)
- `_try_mcp_delegation` → `_try_service_delegation` (`_index.py`)
- `_print_mcp_results` → `_print_service_results`, plus the private
  `_print_mcp_async_results` → `_print_service_async_results` (`_index.py`)

Orchestrator follow-up after the executor pass: removed a `_display_mcp_error`
backward-compat alias the executor had left in `cli/__init__.py` (the deconflation ADR
mandates a hard clean cut with no shims) and updated the sole consumer
`tests/test_cli.py` to import `_display_service_error` directly. Also fixed the stale
`via` enum: `Literal["mcp", "in-process"]` → `Literal["service", "in-process"]` and the
two `tests/test_cli.py` call sites that still passed `via="mcp"`.

## Outcome

No old identifiers remain anywhere in `src/` (grep-verified). `ruff` and `ty` clean; the
full `test_cli.py` suite (183 cases) passes.

## Notes

`cli/_mcp_admin.py` was intentionally left untouched — it controls the genuine MCP stdio
protocol server, where `mcp` naming is correct.
