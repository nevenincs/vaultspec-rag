---
tags:
  - '#research'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:4eb4f7d499f45a0924658fa896bd0c67c31db2f007ae44704ec20eab7d2538c0'
related:
  - "[[2026-07-27-lint-defaults-ruff-complexity-reference]]"
---

# `lint-defaults` research: `ruff complexity remediation`

The question is whether the project can restore Ruff's upstream complexity
defaults without obscuring public contracts or weakening lint. The evidence favors
real decomposition for internal behavior and a small, explicit exception policy for
true CLI and MCP boundaries; the ADR must decide whether those boundaries remain
directly shaped by their transport contracts.

## Findings

### Raised global maxima conceal new complexity

The active configuration selects the three stable rules and gives all four rules
ratchet-only maxima above Ruff's upstream defaults. The upstream-threshold check
therefore exposes 279 existing findings, while the configured gates pass.
`pyproject.toml:191-243`; `justfile:175`; `2026-07-27-lint-defaults-ruff-complexity-reference`.

### Internal operations have existing decomposition precedents

The codebase already represents cohesive policy and limits as dedicated values, and
extracts named phases or accumulator state without changing orchestration. These
patterns allow internal functions to preserve ordering, errors, and return values
while meeting the lower limits. `src/vaultspec_rag/search/_noise.py:36-70`;
`src/vaultspec_rag/indexer/_consumer_pipeline.py:82-124`;
`src/vaultspec_rag/server/_main.py:54-149`; commit `f52d7b88`.

### Transport boundaries are a distinct option

CLI and MCP entry points intentionally expose independently owned user filters as
direct parameters. Replacing them with internal parameter objects may make the
transport contract less legible without reducing the underlying decisions. A narrow,
reviewed rule-specific exception at such boundaries is an alternative to preserving
the raised global maxima; a wholesale exception rollout would hide the same debt in
many locations. `src/vaultspec_rag/cli/_search.py:903-1002`;
`src/vaultspec_rag/mcp/_tools.py:359-430`.

### Uninvestigated scope

This research did not assess whether every public signature is externally stable.
The implementation phase must classify each public boundary from its actual callers
before choosing a parameter object or a documented local exception.

## Sources

- `pyproject.toml:191-243`
- `justfile:175`
- `src/vaultspec_rag/search/_noise.py:36-70`
- `src/vaultspec_rag/indexer/_consumer_pipeline.py:82-124`
- `src/vaultspec_rag/server/_main.py:54-149`
- `src/vaultspec_rag/cli/_search.py:903-1002`
- `src/vaultspec_rag/mcp/_tools.py:359-430`
- commit `f52d7b88`
