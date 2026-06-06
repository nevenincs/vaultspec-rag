---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
step_id: 'S07'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

# Update existing integration tests to assert against the backend API

## Scope

- `src/vaultspec_rag/tests/test_cli.py`

## Description

- Create `TestBenchmarkAndQualityCommands` unit test class inside `src/vaultspec_rag/tests/test_cli.py`.
- Add test asserting successful delegation, parameter mapping, and output formatting of the CLI `benchmark` command.
- Add test asserting correct exit code 1 handling of the CLI `benchmark` command when the vault is empty.
- Add test asserting successful delegation and PASS/FAIL output rendering of the CLI `quality` command.

## Outcome

- Successfully added comprehensive unit test coverage for decoupled benchmark and quality commands and APIs.

## Notes
