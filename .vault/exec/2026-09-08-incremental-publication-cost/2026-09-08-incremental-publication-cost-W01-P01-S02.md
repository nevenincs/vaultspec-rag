---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:cf76721fa01c8c457b837f97fe63211c50f349af182f0551e8474a548b9280af'
step_id: 'S02'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Prove add, modify, delete, rename, empty, ignored, rejected, and no-op delta behavior

## Scope

- `src/vaultspec_rag/tests/test_publication_proof.py`

## Changes

- `A` `src/vaultspec_rag/tests/test_publication_proof.py`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/tests/test_publication_proof.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/tests/test_publication_proof.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/tests/test_publication_proof.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/tests/test_publication_proof.py` -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py` -> `fail`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_publication_proof.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
