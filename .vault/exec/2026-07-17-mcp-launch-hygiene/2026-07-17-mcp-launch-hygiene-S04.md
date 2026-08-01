---
tags:
  - '#exec'
  - '#mcp-launch-hygiene'
date: '2026-07-17'
modified: '2026-07-17'
body_hash: 'sha256:cf97e15ca2394c1228cb58f6a8616b009c1335dd7ed245052f2192dda3d12b10'
step_id: 'S04'
related:
  - "[[2026-07-17-mcp-launch-hygiene-plan]]"
---

# Document the pre-parity workspace remediation (install --upgrade seed refresh) in the installation guide

## Scope

- `docs/installation.md`

## Description

- Document the pre-parity remediation in the Upgrade section of the
  installation guide: `install --upgrade` rewrites the static exe-form MCP
  seed to the tokenized form, and clients should re-run MCP setup after.

## Outcome

mdformat clean.

## Notes

None.
