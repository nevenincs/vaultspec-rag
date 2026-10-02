---
tags:
  - '#reference'
  - '#monitor-tooling'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:bd3988fd8ae908e1641a417bc11c2059720bbb211734410f5f4eabcbeb0a657d'
related: []
---

# `monitor-tooling` reference: `Shared frontend harness and port registry`

Sources: `Y:/code/devservers-worktrees/main` at commit
`4b25caa896e59bedc51848e8b85b370307b0426a`, and
`Y:/code/vaultspec-marketing-worktrees/main` at commit
`af28bc0639e25d68c4ec2719459a21ac83632c74`.

## Summary

The authorized trust correction is committed in
`Y:/code/devservers-worktrees/rag-monitor-ci` at
`b15e302441c426ba3604ec8ce2178bcfe8b394af`.
Its template admits a ready owner/collaborator pull request or a same-repository
pull request explicitly labeled by a person. Forks and bot labels do not admit
untrusted authors: `Y:/code/devservers-worktrees/rag-monitor-ci/dev/devserver.py:119`.
This consumer adopts that script and template byte-for-byte. The main registry
will report template drift until the upstream feature branch lands; no default
branch was changed.

- The frontend manifest owns the name, twenty-port block and service ports.
  The parser discovers only root manifests and manifests one directory below
  the repository root: `Y:/code/devservers-worktrees/main/dev/devserver.py:197`.
  A manifest solely in `src/monitor` would not be enrolled. A root manifest
  can instead point Vite at that application directory.
- The canonical script pins React and react-dom 19.3.0, Vite 8.3.1 and
  plugin-react 6.1.1. It renders the lifecycle recipe and workflow and checks
  exact manifest and lockfile versions, recipe text, workflow text and port
  literals: `Y:/code/devservers-worktrees/main/dev/devserver.py:69`,
  `Y:/code/devservers-worktrees/main/dev/devserver.py:1049`.
- Registry discovery falls back to main when a requested worktree is absent.
  Cross checks reject overlapping blocks, duplicate names, reserved services
  and Windows exclusions:
  `Y:/code/devservers-worktrees/main/tools/common.py:49`,
  `Y:/code/devservers-worktrees/main/tools/registry.py:63`.
  On 2026-09-30, `just ports --worktree monitor --json` showed 5420-5439
  available and one unrelated cadrumo-marketing workflow drift finding.
- The sync tool installs the script and rendered workflow without rewriting
  unrelated recipes: `Y:/code/devservers-worktrees/main/tools/sync.py:28`.
- Vite reads declared ports and enables strictPort in both development and
  preview: `Y:/code/vaultspec-marketing-worktrees/main/web/vite.config.ts:423`.
  Its frontend uses npm, ESLint with typescript-eslint and React Hooks rules,
  and strict TypeScript:
  `Y:/code/vaultspec-marketing-worktrees/main/web/package.json:1`,
  `Y:/code/vaultspec-marketing-worktrees/main/web/eslint.config.js:1`,
  `Y:/code/vaultspec-marketing-worktrees/main/web/tsconfig.json:1`.
- The harness starts Vite with explicit strict ports, reattaches by identity
  and fingerprint, and aliases the route through portless. State lives outside
  checkouts: `Y:/code/devservers-worktrees/main/dev/devserver.py:484`,
  `Y:/code/devservers-worktrees/main/dev/devserver.py:600`,
  `Y:/code/devservers-worktrees/main/dev/devserver.py:756`.
  CI proves start, reattach and stop:
  `Y:/code/devservers-worktrees/main/dev/devserver.py:1126`.
- Tailnet HTTPS maps declared ports at a fixed offset, but its generator reads
  main checkouts only:
  `Y:/code/devservers-worktrees/main/tools/tailnet.py:32`.
  A feature-worktree mapping therefore needs an explicit tailscale serve
  command until the declaration lands on main.
- The shared script's owner uses Ruff with a 120-column limit and a narrower
  rule set: `Y:/code/devservers-worktrees/main/pyproject.toml:24`.
  Applying RAG's current Ruff configuration to the canonical script reports
  101 findings. Altering the copy would violate byte parity.
