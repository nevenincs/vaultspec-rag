---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:74b9d2b547c8dc95b52e31db1e1416bf38f9e3e8d12da8300860b4179dc71b8a'
step_id: 'S15'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Add the restore verb to the storage command group as a thin adapter over the storage operation, carrying the group's dry-run preview, confirmation, and unreachable-server exit codes

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

Add the restore verb to the storage command group as a thin adapter over the storage operation, carrying the group's dry-run preview, its confirmation contract, and its unreachable-server exit code.

## Outcome

Delivered as `storage_restore` in `src/vaultspec_rag/cli/_service_storage.py`, registered as `vaultspec-rag server storage restore`.

A thin adapter, as the phase requires: every refusal, the destination derivation, and the provenance carry stay in the storage operation. The verb supplies only what the group already owns - the dry-run preview, the `--yes` confirmation with `--json` requiring it, and the exit-3 unreachable-server path through the shared `_run_storage_op`.

It adds one check of its own: a missing archive directory exits 2 with `archive_not_found` before any client opens, so an operator typo is answered as a typo rather than as a service-health question.

Exit codes: 0 on `restored` and on an explicit `--dry-run` preview; 1 on any refusal and on an unrequested preview, since neither achieved the requested state; 2 on a missing archive and on `--json` without `--yes`; 3 when the server is unreachable.

## Notes

The verb adds one check the storage operation does not own: a missing archive directory exits 2 before any client opens. That belongs at the adapter because it is an operator input error, and routing it through the server would answer a mistyped path with a service-health verdict.

Everything else is delegated. The verb computes no prefix, judges no destination, and writes no manifest entry.
