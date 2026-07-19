---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-19'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# `storage-namespace-hygiene` `P02` summary

Steps S08-S10 complete. Commit 7ae79ca plus the audit-driven doc note.

- Modified: `src/vaultspec_rag/cli/_service_storage.py`, `src/vaultspec_rag/tests/test_storage_adversarial.py`, `docs/cli.md`, `docs/storage-maintenance.md`

## Description

Gave consumers and test harnesses a sanctioned per-root teardown: `server storage delete --root PATH` resolves the path against the operator's cwd, derives the prefix through the one real `root_collection_prefix` derivation, and dispatches through the unchanged `delete_prefix` safety gates; the resolved root and prefix are echoed as `queried_root`. Deletion is idempotent in both addressing forms - an absent namespace reports `already_absent` and exits 0 - satisfying the broker already-satisfied-is-success contract; exactly-one addressing is enforced with a structured exit-2 rejection. Covered by 7 CLI tests (addressing matrix, resolution parity, outcome mapping, envelope shape). Docs updated across the CLI reference and the storage-maintenance guide, including the harness-teardown recipe and the freshness semantics; the reviewer's medium finding (the remap also applies to the prefix form) was resolved by documenting the uniform behavior - the verb has never shipped in a release, so no consumer breaks.
