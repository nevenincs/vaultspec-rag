---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S13'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# create a provisioning front-door module that orchestrates torch, model, and qdrant provisioning and returns a heterogeneous per-dependency result

## Scope

- `src/vaultspec_rag/commands/_provision.py`

## Description

- Create `_provision.py` as the unified opt-out provisioning front door over the existing torch, model, and qdrant backends.
- Define `ProvisionStep` (torch/models/qdrant) and `ProvisionAction` (the shared sync vocabulary plus `dry_run`) as closed StrEnum vocabularies.
- Define `ProvisionStepResult` carrying step, action, detail, and a `sync_pending` flag for the heterogeneous two-phase torch step.
- Define `ProvisionOutcome` holding one result per considered dependency with an aggregate `status` (failed/mixed/common-action), `ok`, `result_for`, and JSON `to_dict`.
- Add `provision_dependencies(target, local_only, skip, dry_run, configure_torch, assume_yes, sync_after, confirm)` sequencing the three steps and returning the heterogeneous outcome.

## Outcome

The orchestration front door exists and returns a heterogeneous per-dependency `ProvisionOutcome`. Default polarity is opt-out: every step runs unless `local_only` (skips qdrant) or a finer `skip` token drops it. Each result is in the shared sync vocabulary; skipped steps stay represented so the report is complete. The API shape serves the later setup-CLI phase (W02.P05), which threads the outcome into the install report (W02.P06).

## Notes

The model-ensure step (S15) was hosted in `_provision.py` rather than `commands/_models.py` to keep the whole P04 contribution inside the single module this executor exclusively owns. A concurrent process in the shared worktree was actively reverting unstaged edits to `_models.py`, which W02.P06 (S22) also targets; relocating the function avoided a cross-agent write collision without changing the public surface, since `provision_models` is exported from the commands package either way.
