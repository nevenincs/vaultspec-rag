---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:23c8f0ebb68369b0c4eac1a999c4defe511d37313b7afb12bdd1d8f3f8daaf96'
step_id: 'S15'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace maintainability-remediation with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S15 and 2026-07-27-maintainability-remediation-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Verify the maintainability floor and all focused real-behavior regressions and ## Scope

- `tools/health_report.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify the maintainability floor and all focused real-behavior regressions

## Scope

- `tools/health_report.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

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
