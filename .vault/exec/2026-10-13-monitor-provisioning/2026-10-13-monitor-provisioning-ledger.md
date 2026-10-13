---
tags:
  - '#exec'
  - '#monitor-provisioning'
date: '2026-10-13'
modified: '2026-10-13'
body_schema: 'body-v2'
body_hash: 'sha256:3ea855e552d9f7d89d48a54bd0e0959f32318dd03bf8cbe0274f34125d807b5b'
related:
  - "[[2026-10-13-monitor-provisioning-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `monitor-provisioning` ledger

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

- `S01` `A` `src/vaultspec_rag/native_binary/__init__.py`
- `S01` `A` `src/vaultspec_rag/native_binary/_install.py`
- `S01` `R` `src/vaultspec_rag/qdrant_runtime/_download.py` -> `src/vaultspec_rag/native_binary/_download.py`
- `S01` `R` `src/vaultspec_rag/qdrant_runtime/_executable_hold.py` -> `src/vaultspec_rag/native_binary/_hold.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_managed_install.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_provision.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_spawn_trust.py`
- `S01` `M` `src/vaultspec_rag/tests/_fake_qdrant_binary.py`
- `S01` `M` `src/vaultspec_rag/tests/_qdrant_provision_seam.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_helpers_qdrant_mirror.py`
- `S01` `M` `src/vaultspec_rag/tests/test_cli_progress_surfaces.py`
- `S01` `M` `src/vaultspec_rag/tests/test_provision.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_download.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_download_faults.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_executable_hold.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_install.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_offline_install.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_restart_accounting.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_runtime.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_spawn_trust.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_store_format.py`
- `S01` `M` `src/vaultspec_rag/tests/test_start_provisioning.py`
- `S01` `M` `tools/binaries/bun_toolchain.py`
- `S01` `M` `tools/binaries/tests/test_bun_toolchain.py`
- `S01` `M` `tools/monitor/acquire.py`
- `S01` `M` `tools/monitor/build.py`
- `S01` `M` `tools/monitor/frontend.py`
- `S01` `M` `tools/monitor/linux_exec.py`
- `S01` `M` `tools/monitor/offline.py`
- `S01` `M` `tools/monitor/provenance.py`
- `S01` `M` `tools/monitor/release.py`
- `S01` `M` `tools/monitor/smoke.py`
- `S01` `M` `tools/monitor/tests/test_frontend.py`
- `S01` `M` `tools/qdrant_pin_digests.py`
- `S01` `verify:` `uv run --no-sync ruff check src tools dev conftest.py` -> `pass`
- `S01` `verify:` `uv run --no-sync ruff format --check src tools dev conftest.py` -> `pass`
- `S01` `verify:` `uv run --no-sync ty check src tools dev conftest.py` -> `pass`
- `S01` `verify:` `uv run --no-sync pytest test_qdrant_* test_provision test_managed_install test_start_provisioning test_cli_progress_surfaces test_config_operator_binary tools/binaries/tests tools/monitor/tests -q` -> `pass`
- `S01` `by:` `implementation-engineer-high`

## Notes

- `S01` The lift moved two modules, so five orientation documents under .vaultspec/skills/start-vaultspec-rag/references/ now link to `src/vaultspec_rag/qdrant_runtime/_download.py` and `_executable_hold.py,` which no longer exist, and the documentation link check fails on 14 such links. Those files are user-owned policy sources and were left untouched.
- `S01` No managed-install state machine was lifted beyond the digest, staging and single-member extraction primitives: the free-space admission, the atomic replace remedy, the provisioning lock and the manifest carry Qdrant-specific wording and stay with their owner. The transport and the executable hold moved because they name nothing Qdrant-specific and a second owner would have had to import across runtime packages.
