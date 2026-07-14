---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S02'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Delete the Windows AppContainer backend module (profile derivation, icacls grants, Job Object wrap, pipe plumbing)

## Scope

- `src/vaultspec_rag/indexer/_hook_sandbox_windows.py`

## Description

- `git rm` the Windows AppContainer backend (profile derivation, `CreateProcessW` with security capabilities, `icacls` SID grants, the `_GRANTED` memo, Job Object wrap, pipe plumbing).

## Outcome

Module deleted; no production references remain.

## Notes

The AppContainer profile created on operator machines persists in the OS until manually deleted; it is inert without a launcher.
