---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:25937d9ef30cdb5cd48d510b52bb4d030b9e3193613550111721c37569093313'
step_id: 'S40'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Prove missing or old-format proof, schema drift, and corrupt receipts require typed rebuild refusal and that audit verification cannot seed proof

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `src/vaultspec_rag/tests/test_document_index_escalation.py`

## Changes

- `M` `.vault/plan/2026-09-08-incremental-publication-cost-plan.md`
- `A` `.vault/audit/2026-09-09-incremental-publication-cost-s40-fail-closed-proof-audit.md`
- `M` `.vault/index/incremental-publication-cost.index.md`
- `M` `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `M` `src/vaultspec_rag/tests/test_document_index_escalation.py`
- `verify:` initial audit guards against pre-S40 production -> `fail`
- `verify:` typed rebuild-result classification mutation across six audit cases -> `fail`
- `verify:` missing-ledger state-creation mutation -> `fail`
- `verify:` malformed receipt decoder before dedicated translation -> `fail`
- `verify:` restored mutation guards -> `pass`
- `verify:` `uv run --no-sync pytest -q src/vaultspec_rag/tests/test_document_index_escalation.py` -> `pass`
- `verify:` combined integrity, publication, and concurrency regression gate (83 passed) -> `pass`
- `verify:` `uv run --no-sync ruff check <scoped Python files>` -> `pass`
- `verify:` `uv run --no-sync ruff format --check <scoped Python files>` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag` -> `pass`
- `verify:` `uv run --no-sync basedpyright <scoped Python files>` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md --json` -> `pass`
- `verify:` `vaultspec-core vault check all --feature incremental-publication-cost --no-hints --json` -> `pass`
- `verify:` independent S40 architecture and correctness re-review -> `pass`
