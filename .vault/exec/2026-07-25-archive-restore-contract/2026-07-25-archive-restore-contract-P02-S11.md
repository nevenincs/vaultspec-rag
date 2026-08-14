---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:baf5bbf915c0fa83fc39e736314ccd80d3f3149ddea1fa4291d5871292e13718'
step_id: 'S11'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Cover every refusal and the identity carry with guard tests, and prove each fails when its refusal is lifted or its carry reverted to current values

## Scope

- `src/vaultspec_rag/tests/test_storage_restore.py`
- `src/vaultspec_rag/tests/_storage_archive.py`

## Description

Cover every refusal and the archived-provenance carry with guard tests, and prove each one fails when its refusal is lifted or its carry reverted to current values.

## Outcome

Ten tests in `src/vaultspec_rag/tests/test_storage_restore.py`, covering the reader's refusals, the operation's refusals, the dry run, and the provenance carry.

The refusals that must ask a server what it already holds are driven against a real in-memory Qdrant client - a genuine client over genuine local storage, not a stand-in. Every refusal asserted lands before any snapshot recovery, so the local backend's absent snapshot API is never relied on.

The archive builder both restore test modules needed now has one home in `_storage_archive.py`, rather than a copy in each.

One refusal is not covered here and is not coverable here: an applied restore into a populated destination on a non-Windows server. This platform refuses the applied path before reaching it, which is exactly why `P03` exists.

## Notes

Failure proofs, each applied alone, observed, then reverted, with the suite returning green:

| Guard | Mutation | Observed |
| --- | --- | --- |
| empty snapshot | dropped the `st_size <= 0` half of the file check | DID NOT RAISE |
| archived generation | returned the current schema version | `assert 2 == 1` |
| local-mode ordering | moved the check below `read_archive` | `RuntimeError: archive manifest is unreadable` |
| populated destination | dropped the `if existing:` refusal | reason read `windows_server_archive_restore_unsupported` |
| dry run | removed the short circuit | `NotImplementedError` from the snapshot recovery API |
| identity carry | restamped the current generation | `assert 2 == 1` |
| identity-less archive | invented an identity for each collection | non-empty mapping against `== {}` |

Two did not land where they were first written, and the test docstrings record what actually happened rather than what was expected:

The populated-destination guard fails on `reason`, not `status`. With the refusal removed, this platform still refuses the applied restore for its own reason, so `status` stays `refused`. A later reader narrowing that test to `status` alone would leave a guard that passes with the refusal deleted; the docstring says so.

The dry-run guard fails before its own assertions, by reaching the snapshot recovery API at all. That is the proof rather than a weakness: reaching recovery is the defect, and on this backend it cannot be attempted quietly.
