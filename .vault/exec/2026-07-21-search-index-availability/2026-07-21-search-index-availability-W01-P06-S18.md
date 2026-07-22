---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S18'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Add a real MCP stdio call proving unavailable search yields CallToolResult isError true and never structured empty results using Sol medium

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Start the production Model Context Protocol stdio entrypoint through the official client transport.
- Initialize an official `ClientSession` before admitting its `search_vault` call through the common six-party barrier.
- Assert a recoverable tool error with actionable unavailable-index text and no structured results.

## Outcome

The real stdio consumer boundary now proves that `index_unavailable` becomes
`CallToolResult.isError: true`. Its text includes the jobs command, while structured content
is absent or cannot contain a `results` member.

## Notes

Initialization and tool calls use explicit bounded timeouts, and failure evidence remains
token-redacted and size-bounded. Formatting, lint, strict BasedPyright, and test collection
passed. The focused graphics processing unit runtime was not run because the CUDA lane
remained occupied; acceptance remains deferred to the review gate.
