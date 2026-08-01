---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:a7d838a65272cb9bcc92e820a7bd3b876446e0854707fb658d0130f052e1f561'
step_id: 'S31'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Restore malformed-project error reporting and prove successful mode declarations

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `mode and torch contract tests`
- `and isolated real CLI gates`

## Description

- Preserve fail-closed MCP placement preflight on malformed TOML while constructing the established torch-config error classification and diagnostic.
- Prove non-zero CLI failure, byte-inert project state, empty lifecycle results, and no lock creation on malformed input.
- Use matching runtime and development declarations for successful explicit-mode acceptance.
- Prove enabled intent, disabled intent, MCP-only skip, and combined Core/MCP skip mode-persistence contracts.
- Isolate the Qdrant CLI test's machine lock under temporary storage without stopping the operator's global service.

## Outcome

Malformed project input still stops before source, dependency, mode, provider, ownership,
or lock mutation, now with both structured MCP failure and the established torch-config
error report. Valid tool, dependency, and development operations persist their package
mode with enabled or disabled MCP intent. MCP-only skips persist non-MCP mode intent;
combined Core/MCP skips retain the prior declaration. The real missing-Qdrant CLI path
is deterministic beside an unrelated live global service.

## Notes

The focused 12-case regression matrix and the complete 176-test mode, torch, Qdrant CLI,
and install-integration selection passed. Ruff, formatting, Ty, BasedPyright, all
complexity gates, lock validation, and `git diff --check` passed.
