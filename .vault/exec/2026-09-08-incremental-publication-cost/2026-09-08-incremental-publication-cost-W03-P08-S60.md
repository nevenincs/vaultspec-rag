---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:116bbbec09f08edfd75c8b24e7cb3c628415846f4636021922239052886716a1'
step_id: 'S60'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Implement and activate service-owned CLI full audit verification using an atomic current-proof snapshot and bounded backend payload scans without creating or repairing proof, and permit only rebuild publication to establish missing proof

## Scope

- `src/vaultspec_rag/_index_integrity.py`
- `src/vaultspec_rag/cli/_index.py`
- `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `src/vaultspec_rag/store_catalog.py`
- `src/vaultspec_rag/serviceclient/_transport.py`
- `src/vaultspec_rag/server/_routes_reindex.py`
- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/tests/test_index_integrity.py`
- `src/vaultspec_rag/tests/test_cli_index.py`
- `src/vaultspec_rag/tests/test_server_routes.py`
- `src/vaultspec_rag/tests/test_store.py`

## Changes

- `M` `.vault/plan/2026-09-08-incremental-publication-cost-plan.md`
- `A` `.vault/audit/2026-09-09-incremental-publication-cost-s60-canonical-proof-verification-audit.md`
- `M` `.vault/index/incremental-publication-cost.index.md`
- `M` `src/vaultspec_rag/_index_integrity.py`
- `M` `src/vaultspec_rag/cli/_index.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_publication.py`
- `M` `src/vaultspec_rag/server/_routes.py`
- `M` `src/vaultspec_rag/server/_routes_reindex.py`
- `M` `src/vaultspec_rag/serviceclient/_transport.py`
- `M` `src/vaultspec_rag/store_catalog.py`
- `M` `src/vaultspec_rag/tests/test_cli_index.py`
- `M` `src/vaultspec_rag/tests/test_index_integrity.py`
- `M` `src/vaultspec_rag/tests/test_server_routes.py`
- `M` `src/vaultspec_rag/tests/test_store.py`
- `verify:` missing canonical audit owner/CLI transport guards -> `fail`
- `verify:` removed audit-authority guards at owner, route, and transport -> `fail`
- `verify:` removed missing-ledger and open-receipt refusal guards -> `fail`
- `verify:` removed final proof-token validation -> `fail`
- `verify:` widened backend audit page beyond bounded ledger lookup -> `fail`
- `verify:` treated unretained backend point as retained -> `fail`
- `verify:` reconciled storage during audit read -> `fail`
- `verify:` permitted audit source alias before transport -> `fail`
- `verify:` ignored raw physical point identity -> `fail`
- `verify:` stringified raw-store identity composition -> `fail`
- `verify:` bypassed current payload-schema validation for code, vault, and document -> `fail`
- `verify:` restored mutation guards -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_index_integrity.py` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_cli_index.py` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_server_routes.py` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_store.py` -> `pass`
- `verify:` `uv run --frozen ruff format --check <all modified Python files>` -> `pass`
- `verify:` `uv run --frozen ruff check <all modified Python files>` -> `pass`
- `verify:` `uv run --frozen ty check src/vaultspec_rag` -> `pass`
- `verify:` `uv run --frozen basedpyright <all modified Python files>` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md --json` -> `pass`
- `verify:` `vaultspec-core vault check all --feature incremental-publication-cost --no-hints --json` -> `pass`
- `verify:` independent S60 architecture and correctness re-review -> `pass`
