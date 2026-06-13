---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-09'
step_id: 'P06.S23'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P06.S23 - conflation guard test

scope: `src/vaultspec_rag/tests/test_no_mcp_server_conflation.py`

## Description

Added a guard test asserting that no `.py` file under `src/vaultspec_rag/cli/` or
`src/vaultspec_rag/server/` contains the phrase "MCP server" (case-insensitive) in any
docstring, help text, or string literal. The test parametrises over every file in those
packages and scans the raw text.

Two exemptions are encoded and documented in the test: the entire `src/vaultspec_rag/mcp/`
package and the single file `src/vaultspec_rag/cli/_mcp_admin.py`. The exemption rationale
is recorded inline — `_mcp_admin.py` is the CLI control surface for the genuine MCP stdio
protocol server (start/stop/status), so "MCP server" there is accurate rather than
daemon-conflation.

## Outcome

Test passes (33 parametrised file-cases) once the `P06.S19`–`S22` string fixes landed. The
terminological boundary from the deconflation ADR is now machine-enforced.

## Notes

The guard is deliberately a substring scan, not an AST walk, because the conflation lives in
prose (docstrings, help, error messages), not in code structure.
