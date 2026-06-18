---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S16'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Align the ecosystem test's documented MCP command surface with the commands that actually ship

## Scope

- `src/vaultspec_rag/tests/integration/test_ecosystem_integration.py`

## Description

- Investigated the ecosystem test and the rule it asserts against: the vaultspec-rag-owned rule source under `.vaultspec/rules/rules/` is the editable source, and it does not contain the phantom `server mcp start` command; it correctly documents `server start`, `install`, `server doctor`, and the `search_vault` / `search_codebase` MCP tools.
- Confirmed the stale text lives only in the test's expected strings: three assertions in the rule-propagation class checked for command and tool names the search-first / server-first rule reframe had already retired, including the phantom `server mcp start` and a `status` command the rule does not document.
- Corrected the test assertions to strings the shipped rule actually contains, derived from the rule source: the header check now asserts `vaultspec-rag` and `semantic search`; the MCP-tools check asserts the two tools the rule documents; the CLI-commands check asserts `search`, `install`, `server start`, and `server doctor`, dropping the phantom command and the absent `status`.

## Outcome

The test and the shipped rule now agree on commands and tools that actually ship. The full ecosystem test file passes. No rule source, generated provider mirror, or `*.builtin.md` snapshot was touched, so no `sync` was required and the forbidden-file boundary was never approached.

## Investigation path

The task offered two paths: fix the rule source and sync, or fix only the test. The rule source was already correct and current (server-first, search-first, no phantom command), so the only stale text was the test's expected strings. The chosen path was therefore to fix only the test assertions, leaving the rule source and all generated mirrors untouched.

## Notes

The stale assertions were pre-existing failures: the rule's server-first / search-first reframe in an earlier wave outpaced the test, which still expected the old GPU-accelerated-search header, the full six-tool surface, and the phantom `server mcp start`. Expected values were derived strictly from the current rule source, never copied from a broken run's output.
