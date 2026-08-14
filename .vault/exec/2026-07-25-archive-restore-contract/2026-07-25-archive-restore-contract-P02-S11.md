---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:2878f62ef8404513d6e8006c94a6849640b0b4072ba57b4c500480d6a3facff9'
step_id: 'S11'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace archive-restore-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S11 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Cover every refusal and the identity carry with guard tests, and prove each fails when its refusal is lifted or its carry reverted to current values and ## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Cover every refusal and the identity carry with guard tests, and prove each fails when its refusal is lifted or its carry reverted to current values

## Scope

- `src/vaultspec_rag/tests/test_storage_restore.py`
- `src/vaultspec_rag/tests/_storage_archive.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

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
