---
tags:
  - '#exec'
  - '#stdio-watchdog-convergence'
date: '2026-07-17'
modified: '2026-07-17'
body_hash: 'sha256:cec4d8ae42fb381b1b15fdb8c5695cb9d44ed2f13f3c0932d8d8aaadeac2bd05'
step_id: 'S02'
related:
  - "[[2026-07-17-stdio-watchdog-convergence-plan]]"
---

# Rework the installer to the layered composition: explicit then resolved client as precise anchors, ancestor chain only when no client resolves, grace sleep only for prunable targets, handles closed on every disarm path

## Scope

- `src/vaultspec_rag/server/_stdio_lifetime.py`

## Description

- Extract `_gather_windows_targets`: explicit override then resolved
  client as precise anchors; the discovered chain arms only when no
  client anchor landed; duplicate handles closed, not leaked.
- `_windows_watchdog` sleeps the grace window only when prunable targets
  exist and never prunes precise anchors.
- `install_stdio_lifetime_watchdog` gains `client_pid` injection for
  tests; module docstring reframed (the grace blind spot now applies to
  the fallback shape only).

## Outcome

ruff (incl. branch-count gate after extraction), basedpyright, ty green.

## Notes

None.
