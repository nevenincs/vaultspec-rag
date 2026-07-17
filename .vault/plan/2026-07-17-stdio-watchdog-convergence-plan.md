---
tags:
  - '#plan'
  - '#stdio-watchdog-convergence'
date: '2026-07-17'
modified: '2026-07-17'
tier: L2
related:
  - '[[2026-07-17-stdio-watchdog-convergence-adr]]'
  - '[[2026-07-17-stdio-watchdog-convergence-research]]'
---

# `stdio-watchdog-convergence` plan

### Phase `P01` - Watchdog convergence

Port the layered-anchor design: pipe-creator resolver, grace-prunable semantics, client-instead-of-chain arming, disarm-path handle hygiene.

- [x] `P01.S01` - Add resolve_stdin_client_pid (GetNamedPipeServerProcessId on the inherited stdin handle, fail-open) and the grace_prunable flag on watched targets; `src/vaultspec_rag/server/_stdio_lifetime.py`.
- [x] `P01.S02` - Rework the installer to the layered composition: explicit then resolved client as precise anchors, ancestor chain only when no client resolves, grace sleep only for prunable targets, handles closed on every disarm path; `src/vaultspec_rag/server/_stdio_lifetime.py`.

### Phase `P02` - Functional assertion floor

Every real-shim test proves served capability over the actual stdio wire; the client-kill scenario composes both issues.

- [x] `P02.S03` - Add unit coverage for the resolver and the layered arming composition; `src/vaultspec_rag/tests/test_stdio_lifetime.py`.
- [x] `P02.S04` - Raise the e2e suite to the floor: stdlib wire harness, handshake plus five-tool surface before EOF, intermediary-client kill with instant reap, degraded-mode search_vault guidance through the wire; `src/vaultspec_rag/tests/integration/test_stdio_lifetime_e2e.py`.

### Phase `P03` - Docs and closeout

Document the anchor layering and close both issues with the audit.

- [x] `P03.S05` - Update the stdio server lifetime docs with the pipe-creator primary anchor and chain fallback; `docs/mcp.md`.

## Description

## Steps

## Parallelization

## Verification
