---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S03'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---
## Outcome

Reconciled the active registry assertion seam. The registry scenarios import the canonical public `AttemptTerminal` model rather than the removed private spelling, keeping persisted attempt completion assertions on the direct job-control contract.

## Verification

- `uv run --no-sync ruff check src/vaultspec_rag/tests/integration/test_jobs_registry.py`
- `uv run --no-sync ty check src/vaultspec_rag/tests/integration/test_jobs_registry.py`
- `uv run --no-sync pytest -p no:cacheprovider src/vaultspec_rag/tests/integration/test_jobs_registry.py -q` â€” 22 passed, including real vault/code reindex record completion.

No unrelated worktree changes were altered.
