---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:12bc68c0e919c7a7245ea237d2a4aea2d8676425a76107fa4c37b98ffe8faaec'
step_id: 'S18'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Add a real MCP stdio call proving unavailable search yields CallToolResult isError true and never structured empty results using Sol medium

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Start the production Model Context Protocol stdio entrypoint through the official client transport.
- Initialize an official `ClientSession` before admitting its `search_vault` call through the
  five-party barrier.
- Assert a recoverable tool error with actionable unavailable-index text and no structured results.

## Outcome

The real stdio consumer boundary now proves that `index_unavailable` becomes
`CallToolResult.isError: true`. Its text includes the jobs command, while structured content
is absent or cannot contain a `results` member.

## Notes

Initialization and tool calls use explicit bounded timeouts, and failure evidence remains
token-redacted and size-bounded. Final local graphics processing unit acceptance passed with
one selected test and seven deselected.
