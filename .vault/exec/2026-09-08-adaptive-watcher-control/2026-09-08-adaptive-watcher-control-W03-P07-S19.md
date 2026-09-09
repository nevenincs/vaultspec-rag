---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:12cb1b804b79604a55f3b338744db715c59966305917145486b90f3c2f39533a'
step_id: 'S19'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Add mutation-proved guards for trailing flush, freshness, refusal, exact recovery, fair rotation, and adapter ownership

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `verify:` `pytest test_quiet_tree_deadline_is_scheduled_and_wakes [observe min removed]` -> `fail`
- `verify:` `pytest test_quiet_tree_deadline_is_scheduled_and_wakes [restored]` -> `pass`
- `verify:` `pytest test_maximum_freshness_caps_ordinary_deferral [freshness addition removed]` -> `fail`
- `verify:` `pytest test_maximum_freshness_caps_ordinary_deferral [restored]` -> `pass`
- `verify:` `pytest test_rebuild_refusal_is_terminal_to_retry_admission [predicate disabled]` -> `fail`
- `verify:` `pytest test_rebuild_refusal_is_terminal_to_retry_admission [restored]` -> `pass`
- `verify:` `pytest test_restart_requires_exact_scope_and_incremental_job_authority [incremental check removed]` -> `fail`
- `verify:` `pytest test_restart_requires_exact_scope_and_incremental_job_authority [restored]` -> `pass`
- `verify:` `pytest test_equal_deadlines_rotate_after_the_previous_selection [turn memory removed]` -> `fail`
- `verify:` `pytest test_equal_deadlines_rotate_after_the_previous_selection [restored]` -> `pass`
- `verify:` `pytest test_adapters_do_not_own_controller_scheduling [adapter symbol added]` -> `fail`
- `verify:` `pytest test_adapters_do_not_own_controller_scheduling [restored]` -> `pass`
- `verify:` `uv run ruff format src/vaultspec_rag/tests/test_adr_regression.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_adr_regression.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_adr_regression.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_adr_regression.py::TestAdaptiveWatcherArchitecture` -> `pass`
