---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S14'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# wrap the torch configurator step in the front door so it reports configured-with-sync-pending through the shared sync vocabulary

## Scope

- `src/vaultspec_rag/commands/_provision.py`

## Description

- Add `_provision_torch` wrapping the existing `_run_torch_config_install` backend against a scratch `InstallReport`.
- Map the backend's `TorchConfigAction` onto the shared vocabulary: `APPLIED` to `created`, `ALREADY` to `unchanged`, `DRY_RUN` to `dry_run`, disabled/absent/declined/skipped variants to `skipped`, conflict/error to `failed`.
- Set `sync_pending=True` whenever the pyproject is configured but the follow-up `uv sync` has not run, and render the honest "sync pending" detail so the two-phase torch step is not mistaken for a fully fetched dependency.

## Outcome

The torch step reports `configured, sync pending` (sync_pending true) on a fresh patch and `unchanged` on a satisfied one, distinct from a fetched binary's terminal `downloaded`/`unchanged`. The heterogeneity the ADR requires is surfaced honestly through the shared vocabulary.

## Notes

The two-phase boundary is the ADR's named friction point: the front door configures torch but the sync is the user's to run, so `sync_pending` is the contract field, not polish. When `sync_after` actually runs the sync, `sync_pending` flips false and the detail drops the "sync pending" suffix.
