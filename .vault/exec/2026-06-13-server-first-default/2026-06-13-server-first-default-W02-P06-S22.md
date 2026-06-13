---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S22'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# extend InstallReport with per-dependency provisioning outcomes and render them honestly in the human and JSON report

## Scope

- `src/vaultspec_rag/commands/_models.py`

## Description

- Verify `InstallReport` carries the heterogeneous per-dependency provisioning
  outcome on its `provision_outcome` field and renders it honestly in the JSON
  report via the `provisioning` key in `to_dict`.
- Confirm the JSON shape is complete and honest: the per-step view carries the
  shared-vocabulary `action`, the `detail` reason, and the torch-only
  `sync_pending` flag, so a JSON consumer sees the two-phase torch state without
  the human renderer.

## Outcome

The `provision_outcome` field and the `provisioning` JSON key landed in the
prior phase already satisfy this Step: the field holds one result per considered
dependency (opted-out steps included, so the report is complete), and `to_dict`
serialises the whole outcome - aggregate `status`, `dry_run`, and the per-step
`action` / `detail` / `sync_pending` triple. The honest two-phase torch state is
preserved in JSON via `sync_pending`. No duplication was introduced; the model
was verified rather than re-implemented. The integration test added in S25
asserts the JSON `provisioning` key is heterogeneous and serialisable.

## Notes

The field and JSON wiring landed in the preceding phase, so this Step was a
verification of the existing contract rather than new model code. The human
rendering of the same outcome is the sibling Step S23.
