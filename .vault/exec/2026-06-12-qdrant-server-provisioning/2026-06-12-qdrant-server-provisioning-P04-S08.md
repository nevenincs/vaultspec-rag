---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
step_id: 'S08'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Add the server qdrant command group with install (upgrade, dry-run, binary, json), bounded status, and yes-gated clean

## Scope

- `src/vaultspec_rag/cli/_service_qdrant.py`
- `src/vaultspec_rag/cli/_app.py`

## Description

- Add `cli/_service_qdrant.py` with the `server qdrant` group registered under the
  server root app: `install [--upgrade] [--dry-run] [--binary PATH] [--json]`
  reporting the sync vocabulary and exiting non-zero on `failed`; `status [--json]`
  bounded to pinned version, active binary with resolution source, up to ten
  provisioned versions, a loopback readyz probe, and the service-recorded child;
  `clean [--keep-current] [--yes] [--dry-run] [--json]` destructive and gated on
  `--yes` with a preview path and a stop-the-service hint when deletion fails on a
  running binary.
- Register `server_qdrant_app` in `cli/_app.py` and export the commands from the
  package init.

## Outcome

`vaultspec-rag server qdrant --help` and subcommand surfaces render; full CLI unit
suite green (202 tests); ty strict passes.

## Notes

None.
