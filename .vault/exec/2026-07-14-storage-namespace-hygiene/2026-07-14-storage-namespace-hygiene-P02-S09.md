---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S09'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Test the delete --root matrix: resolution parity with registration, removed, already_absent exit 0, unknown refusal, and json envelope shape

## Scope

- `src/vaultspec_rag/tests/test_storage_safety.py`

## Description

- Add `TestDeleteRootAddressing` to `src/vaultspec_rag/tests/test_storage_adversarial.py`: both/neither addressing rejected (exit 2, structured envelope), root resolution parity with `root_collection_prefix`, `already_absent` success in json and human modes, unknown-namespace refusal preserved, prefix form unchanged
- Bypass the client with a typed `_run_storage_op` stand-in and a recording `delete_prefix` fake

## Outcome

7 new CLI tests covering the addressing matrix and outcome mapping; all pass. Commit 7ae79ca.

## Notes

Tests were placed in the adversarial suite (the destructive-verb guard module) rather than `test_storage_safety.py` (path containment only); the plan step scope was updated accordingly.
