---
tags:
  - '#exec'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:6b2e9f6a7af6828dce62dd20c1aca54d5957fc1b3158d536d6134d2a605d71ec'
related:
  - "[[2026-09-23-status-messages-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `status-messages` ledger

## Changes

<!-- MECHANICAL LOG, append-only, one row per path touched per Step, written
     by `--row`:
       - `S##` `A` `path`   added
       - `S##` `M` `path`   modified
       - `S##` `D` `path`   deleted
       - `S##` `R` `old` -> `new`   renamed
     Paths are repo-relative, in backticks. No prose: the Step row states the
     intent and the commit carries the diff.

     Optional per-Step rows, written by `--verify` and `--by`:
       - `S##` `verify:` `<command>` -> `pass` | `fail`
       - `S##` `by:` `<persona>`

     Rows are appended in Step order and never rewritten. Only rows in this
     section register a Step as covered. `--note` adds a `## Notes` section
     ONLY on exception (data loss, skipped work, a scaffold left in code, a
     persistent failure), one `S##`-prefixed line each; it is otherwise
     omitted. -->
- `S01` `A` `src/vaultspec_rag/operator_state/__init__.py`
- `S01` `A` `src/vaultspec_rag/operator_state/_installation.py`
- `S01` `A` `src/vaultspec_rag/tests/test_operator_state.py`
- `S01` `verify:` `ruff check, ruff format --check, ty check` -> `pass`
- `S02` `A` `src/vaultspec_rag/operator_state/_service.py`
- `S02` `A` `src/vaultspec_rag/operator_state/_features.py`
- `S02` `M` `src/vaultspec_rag/operator_state/_installation.py`
- `S02` `M` `src/vaultspec_rag/_operator_commands.py`
- `S02` `M` `src/vaultspec_rag/serviceclient/_status.py`
- `S02` `M` `src/vaultspec_rag/cli/_status_render.py`
- `S02` `M` `src/vaultspec_rag/tests/test_operator_state.py`
- `S02` `verify:` `ruff, ruff format, ty on touched files` -> `pass`
- `S03` `A` `src/vaultspec_rag/operator_state/_models.py`
- `S03` `A` `src/vaultspec_rag/tests/test_operator_state_models.py`
- `S03` `M` `src/vaultspec_rag/tests/test_operator_state.py`
- `S03` `verify:` `ruff, ruff format, ty` -> `pass`

## Notes

- `S02` DegradationReason adds JOBS_DEGRADED beyond the ADR's list because the service already emits an 'indexing jobs are degraded' reason; broker exit codes moved into operator_state._service as their single home
- `S03` Envelopes owned by other subsystems (quiesce, qdrant runtime, jobs rollup, device load, capabilities, support profile, index, projects, watcher) travel as owner mappings inside the forbid-extra top-level models

