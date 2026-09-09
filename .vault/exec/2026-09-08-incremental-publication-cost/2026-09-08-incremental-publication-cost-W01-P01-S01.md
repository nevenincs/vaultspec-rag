---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:4d32f8e9483809b4f7b906265d1481cc7f123dbb40427f457269fae6eaf61760'
step_id: 'S01'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Define publication proof identities, path deltas, aggregate arithmetic, receipt states, provenance, and typed failures

## Scope

- `src/vaultspec_rag/indexer/_publication_proof.py`

## Changes

- `A` `src/vaultspec_rag/indexer/_publication_proof.py`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/indexer/_publication_proof.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/indexer/_publication_proof.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/indexer/_publication_proof.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/indexer/_publication_proof.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
