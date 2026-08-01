---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:15043380579b2366cb474bf69b7b01c31a8436af77860a560ffb3a288a654cbf'
step_id: 'S12'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Raise the Core minimum and refresh the lock after the fixed Core release is published

## Scope

- `pyproject.toml, uv.lock, src/vaultspec_rag/commands/_mode.py, src/vaultspec_rag/commands/_install.py, and src/vaultspec_rag/commands/_uninstall.py`

## Description

- Raise the runtime Core floor to the published native-MCP release.
- Refresh the lock from the public package index.
- Replace temporary dynamic MCP lookups with direct published Core imports.
- Resolve Core 0.1.44 in both the project and an isolated public-index environment.
- Re-run provider mode and end-to-end lifecycle acceptance against the released package.

## Outcome

The project declares `vaultspec-core>=0.1.44`, and the lock resolves Core 0.1.44 from
PyPI with the published wheel and sdist hashes. RAG imports `mcp_status`, `mcp_sync`, and
`mcp_uninstall` directly from the released Core API. Forty-one focused metadata and mode
tests plus thirty-seven end-to-end integration tests pass against the published package,
including both real host CLI queries.

## Notes

The Core release is `vaultspec-core-v0.1.44`, source commit
`42e730e462cc445b24050f5dd57a3f4f4cae2003`. An isolated public-index resolve and the
project environment both report version 0.1.44. Ruff, Ty, BasedPyright, and the full
complexity gate pass.
