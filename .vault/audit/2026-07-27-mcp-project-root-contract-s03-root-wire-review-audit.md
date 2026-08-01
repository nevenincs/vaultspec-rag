---
tags:
  - '#audit'
  - '#mcp-project-root-contract'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:a17681457c570c5b48ff40dc2f8a3233f0d456b5646f715059d0b29342ca0be0'
related:
  - "[[2026-07-25-mcp-project-root-contract-plan]]"
---

# `mcp-project-root-contract` audit: `s03 root wire review`

## Scope

Reviewed commits `091a6b0` and `cd05188f` against S03 of the MCP project-root contract plan. The review covers the root-resolution assertion, the live loopback server arrangement, and the scoped conformance test.

## Findings

### test-isolation | high | Test mutates production module state directly

The `service_routes` fixture assigns `server._SERVICE_TOKEN` directly and restores it after the server exits. This is a code mutation from a test and violates the project's no-patch, no-monkeypatch test discipline. The production route test needs an isolation path that supplies authentication without mutating a module-global production value.

### contract-coverage | high | The delivered test does not cover the planned search and reindex wire contract

The test exercises only `get_code_file`. It proves code-file root selection, but it does not establish that omitted and explicit roots reach the daemon payloads for the search and reindex operations named by S03. A service-route test must cover those request shapes through the production server surface.

## Recommendations

Replace the global token assignment with a real service configuration boundary. Add production-route coverage for both search and reindex request payloads, then repeat the focused quality gates and review before changing the execution record or plan state.
