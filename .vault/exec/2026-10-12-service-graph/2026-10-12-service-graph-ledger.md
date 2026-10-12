---
tags:
  - '#exec'
  - '#service-graph'
date: '2026-10-12'
modified: '2026-10-12'
body_schema: 'body-v2'
body_hash: 'sha256:d4090a668d739e721d820072571f58ba5f382970f52c18eb374ad5309a543466'
related:
  - "[[2026-10-12-service-graph-plan]]"
---

# `service-graph` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/graph_cache.py`
- `S01` `M` `src/vaultspec_rag/search/_searcher.py`
- `S01` `M` `src/vaultspec_rag/search/_rerank.py`
- `S01` `M` `src/vaultspec_rag/service.py`
- `S01` `M` `src/vaultspec_rag/_service_eviction.py`
- `S01` `M` `src/vaultspec_rag/tests/test_graph_cache.py`
- `S01` `M` `src/vaultspec_rag/tests/test_vault_chunking_unit.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_performance.py`
- `S01` `verify:` `covering pytest 107 tests and final graph shutdown integration 21 tests` -> `pass`
- `S01` `verify:` `package ruff, changed format, ty, basedpyright` -> `pass`
- `S01` `verify:` `blocking and epoch guard mutations fail and restored pass` -> `pass`
- `S01` `verify:` `installed cold vault 2.98s graph 0.00094s warm 0.59s code 1.87s` -> `pass`
- `S02` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/core/corpus_io.py`
- `S02` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/core/tests/test_corpus_security.py`
- `S02` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/graph/api.py`
- `S02` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/graph/cache.py`
- `S02` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/graph/cache_io.py`
- `S02` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/graph/tests/test_cache.py`
- `S02` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/vaultcore/scanner.py`
- `S02` `verify:` `236 covering tests and 64 cache tests after owner extraction` -> `pass`
- `S02` `verify:` `package ruff, changed format, ty, basedpyright, production pylint` -> `pass`
- `S02` `verify:` `three guard mutations fail and restored guards pass` -> `pass`
- `S02` `verify:` `real graph load 3.17s, single-entry refresh 6.01s, assembly 0.73s, PageRank 0.44s, centrality 0.21s` -> `pass`
- `S02` `verify:` `installed vault query cold 2.11s warm 1.49s code 2.82s` -> `pass`
- `S02` `verify:` `canonical core commit 5cab80da installed source SHA256 and 89 dependency compatibility checks` -> `pass`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/config/config.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/config/read_scope.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/config/tests/test_config.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/core/corpus_io.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/core/windows_paths.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/core/tests/test_corpus_security.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/graph/api.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/graph/algorithms.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/graph/tests/test_graph.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/graph/tests/test_pagerank.py`
- `S03` `M` `Y:/code/vaultspec-core-worktrees/main/dev/experiments/graph_profile.py`
- `S03` `verify:` `523 covering tests; four default deselections` -> `pass`
- `S03` `verify:` `Ruff format ty basedpyright Pylint and core commit gates` -> `pass`
- `S03` `verify:` `five guard mutations fail and restored pass` -> `pass`
- `S03` `verify:` `py-spy and controlled resource measurement recorded in core audit` -> `pass`
- `S03` `verify:` `core 618cdf1c installed hashes and 89 dependencies; live vault 3.289s and 0.587s` -> `pass`
