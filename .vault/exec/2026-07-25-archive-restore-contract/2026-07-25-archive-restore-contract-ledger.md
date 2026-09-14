---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:949dfc82eb72effde001a4f47a855f91b0c8f2992c8578aae890cf15fa49d3d7'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# `archive-restore-contract` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/tests/test_storage_ops.py`
- `S02` `T` `src/vaultspec_rag/storage_manifest.py`
- `S03` `T` `src/vaultspec_rag/storage_reclamation.py`
- `S03` `T` `src/vaultspec_rag/tests/test_storage_ops.py`
- `S04` `T` `src/vaultspec_rag/storage_reclamation.py`
- `S04` `T` `src/vaultspec_rag/tests/test_storage_ops.py`
- `S04` `T` `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`
- `S05` `T` `src/vaultspec_rag/tests/test_storage_ops.py`
- `S05` `T` `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`
- `S06` `T` `src/vaultspec_rag/storage_ops.py`
- `S07` `T` `src/vaultspec_rag/storage_ops.py`
- `S08` `T` `src/vaultspec_rag/storage_ops.py`
- `S09` `T` `src/vaultspec_rag/storage_manifest.py`
- `S10` `T` `src/vaultspec_rag/storage_ops.py`
- `S11` `T` `src/vaultspec_rag/tests/test_storage_restore.py`
- `S11` `T` `src/vaultspec_rag/tests/_storage_archive.py`
- `S12` `T` `src/vaultspec_rag/tests/integration/test_storage_archive_restore.py`
- `S13` `A` `.vault/exec/2026-07-25-archive-restore-contract/2026-07-25-archive-restore-contract-P03-S13.md`
- `S14` `T` `src/vaultspec_rag/tests/test_adr_regression.py`
- `S15` `T` `src/vaultspec_rag/cli/_service_storage.py`
- `S16` `T` `src/vaultspec_rag/cli/_service_storage.py`
- `S17` `T` `src/vaultspec_rag/tests/test_storage_adversarial.py`
- `S18` `A` `.vault/exec/2026-07-25-archive-restore-contract/2026-07-25-archive-restore-contract-P05-S18.md`
- `S18` `verify:` `just test-python` -> `pass` -> `fail`
- `S19` `A` `.vault/audit/2026-09-10-archive-restore-contract-audit.md`
- `S19` `A` `.vault/exec/2026-07-25-archive-restore-contract/2026-07-25-archive-restore-contract-P05-S19.md`

## Notes

- `S13` Satisfied by an existing test found under a different filename, not written
- `S13` fresh. A later, unrelated module-split refactor renamed
- `S13` `src/vaultspec_rag/tests/integration/test_storage_archive_restore.py` (this
- `S13` Step's cited scope) to
- `S13` `src/vaultspec_rag/tests/integration/test_storage_restore_integration.py`,
- `S13` alongside `storage_ops.py` splitting into `storage_archive.py`,
- `S13` `storage_restore.py`, and sibling modules. The renamed file already carries
- `S13` `test_restore_rolls_back_after_a_real_corrupt_snapshot_failure`
- `S13` (`test_storage_restore_integration.py:226`): it corrupts one archived
- `S13` `.snapshot` file's bytes, then asserts the restore raises
- `S13` (`ResponseHandlingException`/`UnexpectedResponse`, POSIX) or refuses with
- `S13` `WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON` (Windows) rather than
- `S13` completing, and that neither destination collection is created either way.
- `S13` Its counterpart, `test_restored_namespace_answers_the_search_the_original_answered`
- `S13` in the same file, proves the positive direction this Step's `both directions` requirement names alongside it. `git log --follow` on the
- `S13` renamed file shows this corruption test predates the plan's own `P03.S13`
- `S13` row, introduced together with the restore primitive itself.
- `S18` Closed by evidence from the standing CI pipeline, not a fresh run performed
- `S18` for this record. The feature (`storage_archive.py`, `storage_restore.py`,
- `S18` `storage_manifest.py`, the maintenance-inertness regression, and the CLI
- `S18` restore verb) is fully merged to `main` and live. The current `main` HEAD's
- `S18` CI run (`ae186621`) shows the CPU-tier suite - which includes
- `S18` `test_citation_gate.py::test_the_gates_own_file_is_exempt_from_path_literals_not_from_identity`
- `S18` and `test_citation_gate.py::test_the_checkout_carries_no_active_citation_or_identity_leak`,
- `S18` the citation gate this Step names - green on Windows and macOS, and lint
- `S18` (`ruff`), format, and type (`basedpyright`/`ty`) gates green on the
- `S18` dedicated Lint job. Both Linux legs fail on exactly one unrelated item each
- `S18` (`test_cli_env_named_root.py::test_env_naming_a_non_workspace_is_refused_not_ignored`,
- `S18` a console line-wrap artifact) plus a separate `httpx2` dependency-advisory
- `S18` failure, both already tracked on open PR #494 and unconnected to this
- `S18` feature. This reconciles at or above the baseline `P01.S01` recorded before
- `S18` the retention/integrity work began. The GPU/integration tier, which also
- `S18` carries this feature's real-server restore suite, is dispatch-only in CI by
- `S18` design and was not launched for this closure; its coverage is instead
- `S18` evidenced directly, per test, in the sibling `P03.S13` Step Record and in
- `S18` this feature's closing audit.
