---
generated: true
tags:
  - '#index'
  - '#stdio-watchdog-convergence'
date: '2026-08-14'
modified: '2026-09-02'
body_schema: 'body-v2'
body_hash: 'sha256:73ebcb8c506467c015ff2f3a361b44014c863ac059a940ff9cf0d5c76b9fc561'
related:
  - '[[2026-07-17-stdio-watchdog-convergence-P01-S01]]'
  - '[[2026-07-17-stdio-watchdog-convergence-P01-S02]]'
  - '[[2026-07-17-stdio-watchdog-convergence-P02-S03]]'
  - '[[2026-07-17-stdio-watchdog-convergence-P02-S04]]'
  - '[[2026-07-17-stdio-watchdog-convergence-P03-S05]]'
  - '[[2026-07-17-stdio-watchdog-convergence-adr]]'
  - '[[2026-07-17-stdio-watchdog-convergence-audit]]'
  - '[[2026-07-17-stdio-watchdog-convergence-plan]]'
  - '[[2026-07-17-stdio-watchdog-convergence-research]]'
---

# `stdio-watchdog-convergence` feature index

Auto-generated index of all documents tagged with `#stdio-watchdog-convergence`.

## Documents

### adr

- `2026-07-17-stdio-watchdog-convergence-adr` - `stdio-watchdog-convergence` adr: `pipe-creator primary anchor and the functional assertion floor` | (**status:** `accepted`)

### audit

- `2026-07-17-stdio-watchdog-convergence-audit` - `stdio-watchdog-convergence` audit: `review of the issue-229/232 convergence`

### exec

- `2026-07-17-stdio-watchdog-convergence-P01-S01` - Add resolve_stdin_client_pid (GetNamedPipeServerProcessId on the inherited stdin handle, fail-open) and the grace_prunable flag on watched targets
- `2026-07-17-stdio-watchdog-convergence-P01-S02` - Rework the installer to the layered composition: explicit then resolved client as precise anchors, ancestor chain only when no client resolves, grace sleep only for prunable targets, handles closed on every disarm path
- `2026-07-17-stdio-watchdog-convergence-P02-S03` - Add unit coverage for the resolver and the layered arming composition
- `2026-07-17-stdio-watchdog-convergence-P02-S04` - Raise the e2e suite to the floor: stdlib wire harness, handshake plus five-tool surface before EOF, intermediary-client kill with instant reap, degraded-mode search_vault guidance through the wire
- `2026-07-17-stdio-watchdog-convergence-P03-S05` - Update the stdio server lifetime docs with the pipe-creator primary anchor and chain fallback

### plan

- `2026-07-17-stdio-watchdog-convergence-plan` - `stdio-watchdog-convergence` plan

### research

- `2026-07-17-stdio-watchdog-convergence-research` - `stdio-watchdog-convergence` research: `pipe-creator anchor and the functional assertion floor`
