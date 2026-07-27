---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S14'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---
## Outcome

Strengthened direct-owner import coverage for moved production seams. The guard now rejects retained legacy modules or package directories, direct imports of them, and imports of incidental module-level bindings from canonical owner modules. The canonical `job_manager` package remains permitted as an owner rather than being incorrectly classified as a deleted facade.

## Verification

- Independent implementation review found and corrected the package-versus-module false pass.
- A temporary legacy `watcher` package triggered the intended guard failure and was removed immediately.
- `uv run --no-sync pytest -p no:cacheprovider src/vaultspec_rag/tests/test_no_reexports.py -q` â€” 5 passed.
- Scoped Ruff, Ty, and diff checks passed.
