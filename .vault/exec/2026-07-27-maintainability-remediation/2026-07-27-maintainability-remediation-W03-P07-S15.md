---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:d6abe4270d980247165ef1897045f6617281fc1064945872141e70ce788afc22'
step_id: 'S15'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# Verify the maintainability floor and all focused real-behavior regressions

## Scope

- `tools/health_report.py`

## Description

Verify that the maintainability floor is removed from the reported modules and that the focused real-behaviour regressions hold, reconciling the result against what this session could actually run.

## Outcome

The floor is removed from all ten modules this plan set out to fix. None of them is at MI 0.00, because none of them exists any longer as the module that scored there - each was divided into owners that all score above the floor:

| Reported module | Owners now | Lowest MI among them |
| --- | --- | --- |
| `cli/_service_jobs.py` | 5 | 3.41 |
| `indexer/_run_ledger.py` | 7 | above floor |
| `job_manager.py` | package | above floor |
| `tests/integration/test_index_job_control.py` | 4 | above floor |
| `tests/integration/test_install.py` | 5 | 0.00 - see below |
| `tests/integration/test_jobs_registry.py` | 5 | 2.47 |
| `tests/integration/test_service_job_control_e2e.py` | 4 | 19.03 |
| `tests/integration/test_service_jobs.py` | 13 | 21.64 |
| `tests/integration/test_service_lifecycle.py` | 5 | 11.72 |
| `tests/integration/test_service_search_diagnostics.py` | 5 | 16.67 |

Gates run and clean over the package: `ruff check` (all checks passed), `ruff format --check` (681 files already formatted), and `ty check` (all checks passed). The module-length gate is satisfied with the longest module at 1488 lines against the 1500 ceiling.

One gap, stated plainly. `tests/integration/test_install_preview_topology.py` is at MI 0.00 - 982 lines, 27 tests in one class. It is not one of the ten reported modules; it is a module the S08 split produced, so this campaign created it. It clears the module-length gate and it is off no other check, but by the standard this plan set, S08's division of `test_install.py` did not finish the job. It divides cleanly along four concerns already visible in its test names - preview/apply parity, rollback and restore after failure, replay-token race preservation, and unsafe-topology refusal - and no open step covers it.

The seven other modules at MI 0.00 (`test_cli_service_status`, `test_indexer_unit`, `test_install_torch_config`, `test_job_manager_quiesce`, `test_server`, `test_storage_ops`, and `watcher_retry.py`) were never in this plan's scope and were at the floor before this wave began.

## Notes

The maintainability index is report-only in the health report, and the report always exits zero. It ranks; it does not gate. Read the floor as a signal about where scenario weight has piled up, not as a pass/fail an automated run will enforce.

The index also falls toward zero as a function of module size, so the list regenerates: divide a module that scored 0.00 and the modules ranked immediately below it rise to the top of the report. That is why this record names the ten modules the plan scoped rather than treating whatever currently occupies the lowest ten rows as the remaining work.

The focused real-behaviour regressions were not executed. The integration scenarios in this wave need the resident service and a GPU tier, and this session was asked to leave the running service alone; verification here is the static gates, the module inventory, and test collection. Running those scenarios is still owed before the wave is trusted end to end.
