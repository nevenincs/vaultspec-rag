---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:bb9155e23ed0394e4e72f28d6b33ed4b267c8a8435d2d1bd33f94aacebd348d1'
step_id: 'S19'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Persist requested RAG mode in MCP preview projections and align tool-mode recovery guidance

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/server/_main.py`
- `and real mode-transition tests`

## Description

- Persist the requested RAG package declaration inside the isolated preview projection.
- Detect real deployed-mode transitions during dry-run without writing the real declaration.
- Reproduce the ordinary skip and force-managed update passes inside the same projection.
- Map temporary diagnostic paths back to the operator's real target.
- Replace blanket uv-add recovery guidance with explicit tool, dependency, and dev placement instructions.
- Add real dependency/dev-to-tool and tool-to-dependency preview-versus-real regressions.

## Outcome

All three transition cases now produce identical preview and real provider outcomes:
one skip and one update for both Claude and Codex, followed by the correct `uvx` or
`uv run` launch. Every preview preserves all workspace bytes and lock paths. The
runtime guidance now keeps tool mode project-inert and names the actual runtime and dev
dependency surfaces. Four focused real-behavior tests pass.

## Notes

Core's public API renders companion definitions from the package declaration, not only
the call's fallback mode. The projection must therefore stage both source intent and
the requested package declaration before reconciliation.
