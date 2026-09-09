---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:a94d408a4669448a06635aea41af76fcf23d5ff9ea2a8fb3aed5aab9de97db40'
step_id: 'S07'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Prove exact current-schema creation, typed rebuild refusal for old formats, corrupt-schema refusal, revision mismatch, tombstones, receipt replay, atomic proof commit, and zero-copy start

## Scope

- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_generation_start_leaves_canonical_publication_projection_unchanged` -> `fail`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_generation_start_leaves_canonical_publication_projection_unchanged` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_changed_parent_revision_refuses_proof_commit_without_mutation` -> `fail`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_changed_parent_revision_refuses_proof_commit_without_mutation` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_late_receipt_transition_failure_rolls_back_the_entire_proof_commit` -> `fail`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py::test_late_receipt_transition_failure_rolls_back_the_entire_proof_commit` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/ruff.exe check src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/ruff.exe format --check src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/ty.exe check src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/basedpyright.exe src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md` -> `pass`
- `verify:` `vaultspec-core vault check all` -> `pass`
