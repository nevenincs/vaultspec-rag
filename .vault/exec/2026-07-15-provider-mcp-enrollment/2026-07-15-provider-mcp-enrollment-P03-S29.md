---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:26e68b30b01cee26bde8849e7eee610a71b8c98fa8ab8298b168b38ffb58a8e5'
step_id: 'S29'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Enforce complete MCP intent skips and transactional placement-mode commits

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/builtins/__init__.py`
- `and real transaction regressions`

## Description

- Filter MCP builtins before seed classification whenever the MCP component is skipped.
- Preflight optional-extra placement before source, mode, provider, ownership, or lock mutation.
- Commit dependency placement and durable package mode through an exact-byte rollback boundary.
- Fail closed on placement conflicts and write failures with structured MCP errors and CLI exit 2.
- Exercise enabled and disabled intent, canonical and drifted sources, both skip sets, drift and ambiguity conflicts, and a genuine filesystem write blocker.

## Outcome

MCP skips now preserve the complete MCP intent domain while ordinary non-MCP Core work
continues where requested. Placement conflicts stop preview and apply before any MCP
surface changes, retain the prior package mode, and produce a failed report. If mode
persistence fails after a placement edit, the exact prior pyproject and ownership bytes
are restored before the operation returns failure.

## Notes

The 13-test focused skip/transaction matrix and all 73 real install integration tests
passed. Ruff, Ty, BasedPyright, formatting, the lock check, all complexity gates, and
`git diff --check` passed. A complete non-integration run exceeded its five-minute
command timeout without emitting a failure or completion result; the independent S30
release audit will repeat the broad gate with a longer capture window.
