---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S01'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

## Outcome

Reconciled the active direct-owner typing change in `cli/_service_jobs.py`: the Typer command override now accepts Click's concrete context type under `TYPE_CHECKING`, preserving the runtime command surface while satisfying static analysis.

## Verification

- `uv run --no-sync ruff check src/vaultspec_rag/cli/_service_jobs.py`
- `uv run --no-sync ty check src/vaultspec_rag/cli/_service_jobs.py`
- `uv run --no-sync pytest -p no:cacheprovider src/vaultspec_rag/tests/test_jobs_admission_display.py src/vaultspec_rag/tests/test_jobs_lifecycle.py src/vaultspec_rag/tests/test_job_resilience.py -q` â€” 47 passed

No unrelated worktree changes were altered.
