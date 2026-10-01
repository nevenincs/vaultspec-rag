---
tags:
  - '#exec'
  - '#monitor-operations'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:6bb407220aa840eeb00231a364af60b500f23d67294e34fa162d2fa57ec320d0'
related:
  - "[[2026-10-01-monitor-operations-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `monitor-operations` ledger

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

- `S01` `M` `src/monitor/server/local-service.ts`
- `S01` `M` `src/vaultspec_rag/_job_evidence.py`
- `S01` `M` `src/vaultspec_rag/indexer/_donor_candidates.py`
- `S01` `M` `src/vaultspec_rag/server/_routes.py`
- `S01` `M` `src/vaultspec_rag/server/_routes_registry.py`
- `S01` `M` `src/vaultspec_rag/server/_routes_search.py`
- `S01` `M` `src/vaultspec_rag/server/_search_activity.py`
- `S01` `M` `src/vaultspec_rag/service.py`
- `S01` `M` `src/vaultspec_rag/storage_manifest.py`
- `S01` `M` `src/vaultspec_rag/tests/test_jobs_degradation.py`
- `S01` `M` `src/vaultspec_rag/tests/test_monitor_browser.py`
- `S01` `A` `src/vaultspec_rag/_git_repository.py`
- `S01` `A` `src/vaultspec_rag/runtime_observations.py`
- `S01` `A` `src/vaultspec_rag/server/_routes_operator.py`
- `S01` `A` `src/vaultspec_rag/server/_routes_runtime.py`
- `S01` `A` `src/vaultspec_rag/server/_search_evidence.py`
- `S01` `A` `src/vaultspec_rag/tests/test_monitor_runtime.py`
- `S01` `A` `src/vaultspec_rag/tests/test_operator_repositories.py`
- `S01` `verify:` `uv run --no-sync pytest test_monitor_runtime test_operator_repositories test_monitor_browser test_jobs_degradation test_search_activity test_storage_manifest test_index_reuse test_store_donor_reads (124 tests)` -> `pass`
- `S01` `verify:` `uv run --no-sync ruff check src/vaultspec_rag` -> `pass`
- `S01` `verify:` `ruff format --check changed Python paths` -> `pass`
- `S01` `verify:` `ty check changed Python paths` -> `pass`
- `S01` `verify:` `basedpyright --pythonpath .venv/Scripts/python.exe changed Python paths (provisioned dependency sources)` -> `pass`
- `S01` `verify:` `backend negative guard mutations and restoration` -> `pass`
- `S01` `verify:` `npm run lint` -> `pass`
- `S01` `verify:` `npm run typecheck` -> `pass`
- `S01` `verify:` `npm run format:check` -> `pass`
- `S01` `by:` `principal with backend agents`
