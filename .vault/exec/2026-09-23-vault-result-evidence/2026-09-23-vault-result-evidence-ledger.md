---
tags:
  - '#exec'
  - '#vault-result-evidence'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:b44f49cb4ecbd2c66e6b27b31dd3e7c7381cff0e0d8fbca481d8d37faff1c05c'
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
- `S06` `M` `src/vaultspec_rag/search/_searcher.py`
- `S06` `M` `src/vaultspec_rag/search/_result_shaping.py`
- `S06` `M` `src/vaultspec_rag/search/_models.py`
- `S06` `M` `src/vaultspec_rag/tests/test_vault_chunking_unit.py`
- `S06` `M` `src/vaultspec_rag/tests/test_document_result_shaping.py`
- `S06` `M` `src/vaultspec_rag/tests/test_typesafe_search.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/_frozen_corpus_evidence.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/test_vault_evidence_gate.py`
- `S06` `M` `src/vaultspec_rag/tests/quality/evidence_baseline.json`
- `S06` `verify:` `unit and adapter tests (384) and resident GPU integration (30)` -> `pass`

## Notes

- `S03` research and ADR speedup figure corrected from the scratch 6.6x to the in-service ~3x; the decision is unchanged
- `S06` test_typesafe_search fixture grown past the 1,200-character passage bound so its snippet-shorter-than-content premise still holds; the assertion is unchanged

