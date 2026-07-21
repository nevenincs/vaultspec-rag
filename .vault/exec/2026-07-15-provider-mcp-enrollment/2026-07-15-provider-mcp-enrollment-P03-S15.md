---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S15'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Implement accurate non-mutating MCP source-overlay previews and real-file API/CLI regressions

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/tests/integration/test_install.py`
- `and src/vaultspec_rag/tests/test_cli.py`

## Description

- Build a minimal temporary project projection from current MCP ownership and native provider files.
- Apply the requested canonical RAG source addition or removal only inside the projection.
- Run Core's public project-scoped dry-run against the projection and preserve its per-provider counters and actions.
- Add real-file API and CLI regressions for fresh additions, existing removal, byte stability, and lock stability.

## Outcome

Fresh `--mcp` previews now report one Claude addition and one Codex addition. Existing
`--no-mcp` previews report one prune for each provider. Both paths use Core's public
0.1.44 lifecycle and leave every real workspace file and lock path unchanged. Focused
Ruff, formatting, and four real integration regressions pass.

## Notes

Core's `enrolled` argument selects hosts rather than desired MCP sources, so the public
API cannot directly express this overlay. The isolated projection avoids a second
renderer and requires no Core release.
