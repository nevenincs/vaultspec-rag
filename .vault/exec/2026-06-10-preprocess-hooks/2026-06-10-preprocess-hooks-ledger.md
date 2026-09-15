---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-10'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:fa6bf3451c614d747896f971149787efcbd023c1397fc5f8ec371bef9783ccec'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# `preprocess-hooks` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/indexer/_preprocess_config.py`
- `S02` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S03` `T` `src/vaultspec_rag/tests/test_preprocess_config.py`
- `S04` `T` `src/vaultspec_rag/indexer/_preprocess_schema.py`
- `S05` `T` `src/vaultspec_rag/tests/test_preprocess_schema.py`
- `S06` `T` `src/vaultspec_rag/indexer/_preprocess_runner.py`
- `S07` `T` `src/vaultspec_rag/config.py`
- `S08` `T` `src/vaultspec_rag/tests/test_preprocess_runner.py`
- `S09` `T` `src/vaultspec_rag/indexer/_preprocess_cache.py`
- `S10` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S11` `T` `src/vaultspec_rag/tests/test_preprocess_cache.py`
- `S12` `T` `src/vaultspec_rag/indexer/_chunk_worker.py`
- `S13` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S14` `T` `src/vaultspec_rag/tests/test_preprocess_worker.py`
- `S15` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S16` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S17` `T` `src/vaultspec_rag/watcher.py`
- `S18` `T` `src/vaultspec_rag/store.py`
- `S19` `T` `src/vaultspec_rag/store.py`
- `S20` `T` `src/vaultspec_rag/tests/test_preprocess_store.py`
- `S21` `T` `src/vaultspec_rag/indexer/_vault_prep.py`
- `S22` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S23` `T` `src/vaultspec_rag/server/jobs.py`
- `S24` `T` `src/vaultspec_rag/cli/_index.py`
- `S25` `T` `src/vaultspec_rag/search/_models.py`
- `S26` `T` `src/vaultspec_rag/server/_models.py`
- `S27` `T` `src/vaultspec_rag/cli/_render.py`
- `S28` `T` `src/vaultspec_rag/cli/_preprocess.py`
- `S29` `T` `src/vaultspec_rag/cli/__init__.py`
- `S30` `T` `src/vaultspec_rag/tests/test_cli_preprocess.py`
- `S31` `T` `src/vaultspec_rag/indexer/_chunking.py`
- `S32` `T` `src/vaultspec_rag/tests/test_indexer_unit.py`
- `S33` `T` `src/vaultspec_rag/indexer/_chunk_worker.py`
- `S34` `T` `src/vaultspec_rag/config.py`
- `S35` `T` `src/vaultspec_rag/tests/test_html_strip.py`
- `S36` `T` `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`
- `S37` `T` `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`
- `S38` `T` `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`
- `S39` `T` `docs/preprocessing-hooks.md`
- `S40` `T` `docs/preprocessing-hooks.md`
- `S41` `T` `README.md`
- `S42` `T` `tmp toy project (manual)`
- `S43` `T` `vaultspec-rag preprocess (manual)`
- `S44` `T` `vaultspec-rag index/search (manual)`
- `S45` `T` `.pre-commit-config.yaml (manual)`
- `S46` `T` `src/vaultspec_rag/indexer/_preprocess_entry.py`
- `S47` `T` `src/vaultspec_rag/indexer/_preprocess_config.py`
- `S48` `T` `src/vaultspec_rag/indexer/_preprocess_runner.py`
- `S49` `T` `src/vaultspec_rag/tests/test_preprocess_entry.py`
- `S50` `T` `src/vaultspec_rag/indexer/_preprocess_runner.py`
- `S51` `T` `src/vaultspec_rag/tests/test_preprocess_runner.py`
- `S52` `T` `src/vaultspec_rag/indexer/_chunk_worker.py`
- `S53` `T` `src/vaultspec_rag/tests/test_preprocess_store.py`
- `S54` `T` `src/vaultspec_rag/indexer/_preprocess_cache.py`
- `S55` `T` `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`
