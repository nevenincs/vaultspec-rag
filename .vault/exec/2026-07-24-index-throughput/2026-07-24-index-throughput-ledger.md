---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:6caf25660f52f21273e40059f1664c7ae743d9c009da17704e6bf2cf14540092'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# `index-throughput` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/server/job_dispatch.py`
- `S01` `T` `job records`
- `S02` `T` `src/vaultspec_rag/tests/`
- `S03` `T` `src/vaultspec_rag/store.py`
- `S03` `T` `indexer terminal paths`
- `S04` `T` `src/vaultspec_rag/tests/`
- `S05` `T` `measured run`
- `S05` `T` `Step Record`
- `S06` `T` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S06` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S07` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S07` `T` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S08` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S08` `T` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S09` `T` `src/vaultspec_rag/config.py`
- `S09` `T` `measured run`
- `S10` `T` `src/vaultspec_rag/tests/`
- `S11` `T` `measured runs`
- `S11` `T` `Step Record`
- `S12` `T` `repository quality gates`
- `S12` `T` `.vault/adr/2026-07-24-index-throughput-adr.md`
- `S13` `T` `git`
- `S14` `T` `src/vaultspec_rag/server/job_manager.py`
- `S14` `T` `src/vaultspec_rag/server/job_models.py`
- `S14` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S14` `T` `src/vaultspec_rag/embeddings.py`
- `S15` `T` `src/vaultspec_rag/store.py`
- `S16` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S17` `T` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S17` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S18` `T` `pyproject.toml`
- `S18` `T` `.python-version`
- `S09` `T` `src/vaultspec_rag/config/_settings.py`
- `S09` `M` `src/vaultspec_rag/config/_settings.py`
- `S09` `verify:` `cadence-8 vault rebuild: 3731 points, 76.714s, peak CUDA allocated 7954.0 MiB, zero OOM` -> `pass`
- `S09` `by:` `/root`

## Notes

- `S09` Uncontended same-host alternating measurement showed only a 0.605% wall-time improvement at cadence 8 (0.467s), below a meaningful tuning signal; retained the safety-first default cadence 1.
