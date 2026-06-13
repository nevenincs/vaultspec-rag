---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S18'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# call the provisioning front door by default from install_run and thread its result into the install report

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/commands/_models.py`

## Description

- Add `provision`, `local_only`, and `provision_skip` parameters to `install_run`.
- After enrollment and the existing torch-config step, call a new `_run_provisioning`
  helper that delegates to `provision_dependencies`, attaching the heterogeneous
  `ProvisionOutcome` to `report.provision_outcome`.
- Fold `"torch"` into the front door's skip set inside `_run_provisioning` because the
  enrollment torch step already configured torch and reports its own two-phase state;
  re-running it would double-prompt and double-report.
- Surface any failed provisioning step as a recoverable warning rather than raising,
  because enrollment already succeeded and provisioning is the re-runnable phase.
- Carry the outcome onto the report by declaring a `provision_outcome` field on
  `InstallReport` and rendering it in `to_dict()` under the `provisioning` key.

## Outcome

- `install_run(..., provision=True)` runs the front door and the structured report
  carries one result per dependency (torch / models / qdrant) plus the aggregate
  status; `to_dict()` emits a `provisioning` sub-document (or `None` when provisioning
  did not run).
- `install_run` defaults `provision=False` so existing programmatic callers and their
  network-free unit tests keep the enrollment-only behaviour; the operator-facing
  opt-out default (`provision=True`) lives at the CLI edge.
- Twelve new wiring tests in `test_install_provision.py` pass; the 99 existing
  install / config / provision unit tests stay green. `ruff` and `ty` clean.

## Notes

`InstallReport.provision_outcome` (a new field on `commands/_models.py`) was required
to thread the result; W02.P06.S22 nominally owns `_models.py`, but S18 cannot satisfy
"thread its result into the install report" without the field, so the minimal field
declaration plus its `to_dict()` rendering landed here. The `_models.py` file showed no
concurrent sibling edits when touched. The honest human rendering of the outcome
(`_render.py`, S23) was intentionally left to W02.P06 and is not part of this Step; the
JSON contract is already complete via `to_dict()`.
