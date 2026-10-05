---
tags:
  - '#exec'
  - '#qdrant-provisioning-trust'
date: '2026-10-05'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:57713fc07e8c6029773a0afd3422af396db3f05d17068a2e03272d4fc9188f21'
related:
  - "[[2026-10-05-qdrant-provisioning-trust-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `qdrant-provisioning-trust` ledger

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

- `S06` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S06` `M` `src/vaultspec_rag/cli/_service_lifecycle.py`
- `S06` `M` `src/vaultspec_rag/cli/_service_qdrant.py`
- `S06` `M` `src/vaultspec_rag/commands/_install.py`
- `S06` `M` `src/vaultspec_rag/commands/_provision.py`
- `S06` `M` `src/vaultspec_rag/tests/test_cli_progress_surfaces.py`
- `S06` `M` `src/vaultspec_rag/tests/test_cli_qdrant.py`
- `S06` `M` `src/vaultspec_rag/tests/test_install_client_role.py`
- `S06` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S06` `A` `src/vaultspec_rag/tests/_qdrant_provision_seam.py`
- `S06` `A` `src/vaultspec_rag/tests/test_client_provisions_nothing.py`
- `S06` `M` `src/vaultspec_rag/tests/test_provision.py`
- `S06` `verify:` `pytest unit lane over 15 covering modules` -> `pass`
- `S06` `verify:` `dev lint python` -> `pass`
- `S06` `by:` `vaultspec-high-executor`
- `S09` `M` `.env.example`
- `S09` `M` `docs/configuration.md`
- `S09` `M` `src/vaultspec_rag/config/_registry.py`
- `S09` `M` `src/vaultspec_rag/config/_schema.py`
- `S09` `M` `src/vaultspec_rag/config/_settings.py`
- `S09` `M` `src/vaultspec_rag/config/_types.py`
- `S09` `M` `src/vaultspec_rag/tests/test_config_backend.py`
- `S09` `A` `src/vaultspec_rag/tests/test_config_sources.py`
- `S09` `verify:` `pytest over HEAD plus the seventeen joint-commit files` -> `pass`
- `S09` `verify:` `ruff, ty, basedpyright on the committed paths` -> `pass`
- `S09` `by:` `vaultspec-high-executor`

## Notes

- `S06` Commits bed82805 and 5c754e91. The 5c754e91 message states 28 tests in `test_provision.py;` the true count is 24. GPU and integration tiers not run: resident service stopped.
- `S09` Commit e605fc13, shared with the S10 downloader half and the S07 reader half because the declared-but-unread settings guards forbid landing settings without their readers. Tree-wide lint type is red on `tests/test_monitor_inventory.py,` which predates this plan.
