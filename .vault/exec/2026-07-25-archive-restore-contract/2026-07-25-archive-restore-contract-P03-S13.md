---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-09-10'
modified: '2026-09-10'
body_schema: 'body-v2'
body_hash: 'sha256:047d1a9f26718d6d4bfddecb57d86459ec56fb48ca1133fc084e4f2196c357b3'
step_id: 'S13'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Prove that round trip can fail by corrupting the archived snapshot body and observing the restore refuse rather than pass quietly, and record both directions

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_archive_restore.py`

## Changes

- `A` `.vault/exec/2026-07-25-archive-restore-contract/2026-07-25-archive-restore-contract-P03-S13.md`

## Notes

Satisfied by an existing test found under a different filename, not written
fresh. A later, unrelated module-split refactor renamed
`src/vaultspec_rag/tests/integration/test_storage_archive_restore.py` (this
Step's cited scope) to
`src/vaultspec_rag/tests/integration/test_storage_restore_integration.py`,
alongside `storage_ops.py` splitting into `storage_archive.py`,
`storage_restore.py`, and sibling modules. The renamed file already carries
`test_restore_rolls_back_after_a_real_corrupt_snapshot_failure`
(`test_storage_restore_integration.py:226`): it corrupts one archived
`.snapshot` file's bytes, then asserts the restore raises
(`ResponseHandlingException`/`UnexpectedResponse`, POSIX) or refuses with
`WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON` (Windows) rather than
completing, and that neither destination collection is created either way.
Its counterpart, `test_restored_namespace_answers_the_search_the_original_answered`
in the same file, proves the positive direction this Step's `both directions` requirement names alongside it. `git log --follow` on the
renamed file shows this corruption test predates the plan's own `P03.S13`
row, introduced together with the restore primitive itself.
