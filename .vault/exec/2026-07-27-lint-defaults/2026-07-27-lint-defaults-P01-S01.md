---
tags:
  - '#exec'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S01'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

# Remediate upstream-default complexity findings

## Scope

- `src/vaultspec_rag/_atomic_write.py`

## Description

- Introduce immutable `JsonWriteOptions` for atomic JSON serialization and durability.
- Migrate every configured production call site without retaining the old signature.
- Add a real-filesystem regression for non-default serialization and cleanup.
- Review the migration and resolve the coverage finding.

## Outcome

`write_json_atomically` now accepts one cohesive options value and its migrated
callers preserve their prior formatting and durability choices. Scoped Ruff and the
focused production-path tests pass.

## Notes

The shared `jobs.py` change was preserved while its one atomic-write call site was
migrated. Two `test_jobs_unit.py` failures remain attributable to the concurrent
job-manager split, not this step.
