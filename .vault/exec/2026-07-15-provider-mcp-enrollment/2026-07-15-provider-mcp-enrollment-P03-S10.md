---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S10'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Add real-behavior dependency-placement tests for existing runtime and dev declarations

## Scope

- `src/vaultspec_rag/tests/test_install_mcp_extra.py`

## Description

- Exercise runtime, PEP 735 dev, and legacy uv dev dependency placement.
- Prove dry-run immutability, exact owned reversal, and tool-mode transition cleanup.
- Prove unowned extras and drifted requirements remain untouched.

## Outcome

Real temporary-project tests now cover placement, ownership, idempotency, conflicts,
and byte-preserving reversal without mocks, stubs, or patched code paths.

## Notes

The focused module passes 15 tests. One initial drift assertion also changed the
ownership marker; narrowing the external edit to the dependency entry correctly proved
the intended drift refusal.
