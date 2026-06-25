---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S15'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Wire the storage group into the CLI app and import registration

## Scope

- `src/vaultspec_rag/cli/_app.py`

## Description

Verified the storage command group is wired into the CLI app and its commands import-
register. Confirmed the app constructs a `server_storage_app` Typer group and mounts it
under the `server` group with the `storage` name, and that the survey, delete, prune, and
migrate commands attach to that group through their command-module import.

## Outcome

The step is genuinely shipped. `vaultspec-rag server storage ...` resolves the survey,
delete, prune, and migrate verbs because the group is registered on the app and its command
module is imported at startup. No code change needed.

## Notes

No code changes; verify-and-tick of work delivered through pull request 196.
