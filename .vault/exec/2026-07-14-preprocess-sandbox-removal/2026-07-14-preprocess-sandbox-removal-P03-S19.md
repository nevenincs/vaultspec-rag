---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:e18f3e73746f5e113a6673e8aaa5cf13d56f5632df30fcdd744bd9a6ba767a67'
step_id: 'S19'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Sweep remaining sandbox mentions from README, cli, and configuration docs

## Scope

- `docs/`

## Description

- Remove the deleted flag/env rows from the CLI and configuration references and the README blurb; state the direct-execution trust model where the sandbox was described.
- Verified `src/vaultspec_rag/builtins/` seeds carry no sandbox mentions (no edits needed).

## Outcome

Zero sandbox/unsandboxed mentions remain outside ADR-name references.

## Notes

None.
