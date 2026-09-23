---
tags:
  - '#exec'
  - '#vault-result-evidence'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:5d1c3fd931419e2c25636a332c7fcde95c98bd1372b0f49db078a8538cb6b675'
related:
  - "[[2026-09-23-vault-result-evidence-plan]]"
---

# `vault-result-evidence` ledger

## Changes

- `S04` `A` `src/vaultspec_rag/_markdown_passages.py`
- `S04` `A` `src/vaultspec_rag/tests/test_markdown_passages.py`
- `S04` `verify:` `fence guard mutation (fence detection disabled) fails on the section equality, restored passes` -> `pass`
- `S03` `M` `src/vaultspec_rag/embeddings.py`
- `S03` `M` `src/vaultspec_rag/service.py`
- `S03` `M` `src/vaultspec_rag/search/_searcher.py`
- `S03` `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `S03` `M` `.vault/research/2026-09-23-vault-result-evidence-research.md`
- `S03` `M` `.vault/adr/2026-09-23-vault-result-evidence-adr.md`
- `S03` `verify:` `service vault search median rerank 1.089s->0.367s, total 1.140s->0.43s` -> `pass`
- `S01` `A` `src/vaultspec_rag/tests/quality/evidence_queries.toml`
- `S01` `verify:` `self-check: 36 gold spans present and unique at the frozen ref, offsets within 5 chars, 20 beyond 3000 chars` -> `pass`
- `S01` `by:` `vaultspec-standard-executor`
- `S02` `A` `src/vaultspec_rag/tests/integration/test_vault_evidence_gate.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/_frozen_corpus_evidence.py`
- `S02` `M` `src/vaultspec_rag/tests/quality/metrics.py`
- `S02` `A` `src/vaultspec_rag/tests/quality/evidence_baseline.json`
- `S02` `verify:` `ruff+basedpyright on gate files` -> `pass`
- `S05` `M` `src/vaultspec_rag/indexer/_vault_prep.py`
- `S05` `M` `src/vaultspec_rag/indexer/_chunking.py`
- `S05` `M` `src/vaultspec_rag/indexer/_chunk_worker.py`
- `S05` `M` `src/vaultspec_rag/indexer/_vault_checkpoint.py`
- `S05` `M` `src/vaultspec_rag/indexer/_index_schema.py`
- `S05` `M` `src/vaultspec_rag/_store_models.py`
- `S05` `M` `src/vaultspec_rag/store_schema.py`
- `S05` `M` `src/vaultspec_rag/store_catalog.py`
- `S05` `M` `src/vaultspec_rag/tests/test_store_schema_parity.py`
- `S05` `M` `src/vaultspec_rag/tests/test_vault_metadata_subset.py`
- `S05` `M` `src/vaultspec_rag/tests/test_vault_chunking_unit.py`
- `S05` `M` `src/vaultspec_rag/tests/test_vault_checkpoint.py`
- `S05` `verify:` `ruff+basedpyright on touched files` -> `pass`

## Notes

- `S03` research and ADR speedup figure corrected from the scratch 6.6x to the in-service ~3x; the decision is unchanged
