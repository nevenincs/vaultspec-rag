---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:71d79db74acd4442cf9637a154f49d9779f6ff2bc24d4bd9f4368d402868808a'
step_id: 'S07'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Render every repair outcome in human mode, not only under JSON

## Scope

- `src/vaultspec_rag/cli/_render.py`

## Changes

- `M src/vaultspec_rag/cli/_render.py`
- `M src/vaultspec_rag/tests/test_tool_torch_repair.py`

## Notes

The refusal detail is emitted as written rather than re-wrapped. It is already
operator-facing lines - one per holder, each naming the remediation its
relation needs - and folding them into a paragraph would bury the pids and the
command. A healthy or inapplicable environment prints nothing, so an install
with no tool problem does not grow a section saying so.

Guard proof, and it caught a real hole rather than confirming the obvious.
Removing the renderer call from the install report failed nothing on the first
attempt: both new tests called the helper directly, so they proved the helper
worked while saying nothing about whether the report reaches it - which is
precisely the defect this Step exists to close, a renderer that never read
`tool_torch_repair` at all. A third test renders a whole `InstallReport`, and
with that in place the same mutation fails on its assertion. Restored; zero
MUTATION markers remain. Gates: ruff, ty, 15 repair tests and 32 CLI install
tests green.
