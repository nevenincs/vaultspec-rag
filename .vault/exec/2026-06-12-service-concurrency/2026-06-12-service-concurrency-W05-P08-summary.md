---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
related:
  - '[[2026-06-12-service-concurrency-plan]]'
---

# `service-concurrency` `W05.P08` summary

All 25 plan steps closed across the five waves; the adversarial validation gate
ran on the live two-root corpus under genuine multi-agent co-load and the epic's
acceptance question - is the throughput cap software or hardware - is answered
with measurements.

- Modified: `src/vaultspec_rag/store.py`, `src/vaultspec_rag/embeddings.py`,
  `src/vaultspec_rag/config.py`, `src/vaultspec_rag/service.py`,
  `src/vaultspec_rag/jobs.py`, `src/vaultspec_rag/watcher.py`,
  `src/vaultspec_rag/search/_searcher.py`, `src/vaultspec_rag/search/_models.py`,
  `src/vaultspec_rag/search/_rerank.py`, `src/vaultspec_rag/indexer/_vault_prep.py`,
  `src/vaultspec_rag/indexer/_vault_indexer.py`,
  `src/vaultspec_rag/indexer/_codebase_indexer.py`,
  `src/vaultspec_rag/indexer/_streaming.py`, `src/vaultspec_rag/mcp/_tools.py`,
  `src/vaultspec_rag/mcp/_admin_tools.py`, `src/vaultspec_rag/mcp/_resources.py`,
  `src/vaultspec_rag/server/_routes.py`, `src/vaultspec_rag/server/_watcher.py`,
  `src/vaultspec_rag/server/_state.py`, `src/vaultspec_rag/server/__init__.py`
- Created: `src/vaultspec_rag/concurrency.py`,
  `src/vaultspec_rag/tests/benchmarks/bench_concurrency.py`,
  `src/vaultspec_rag/tests/benchmarks/baselines/w01_baseline.json`,
  `src/vaultspec_rag/tests/benchmarks/baselines/w05_results.json`,
  `src/vaultspec_rag/tests/test_vault_chunking_unit.py`,
  `src/vaultspec_rag/tests/test_encode_hygiene_unit.py`,
  `src/vaultspec_rag/tests/integration/test_vault_chunking_integration.py`

## Description

The validation gate closed the epic's loop from diagnosis to proof:

- One-time migrations ran on both roots through the automatic marker detection:
  the vault corpus moved to one point per heading-aware chunk (17372 chunks on
  the large root, 1432 on main) and the code corpus re-embedded under the
  contextual-header format. Four rebuild jobs ran concurrently under the index
  limiter with the GPU measured at 100% utilization - the inverse of the
  pre-rework signature where identical load left the GPU idle behind locks.
- The migration surfaced and fixed a quadratic local-store id-scan pathology
  (per-page resort of every point id) that had silently taxed every large-corpus
  scan; clean rebuilds now skip the empty-by-construction snapshot and local id
  scans fetch a single page.
- Post-rework saturation matrix versus the frozen baseline: vault searches trade
  latency for relevance by design (the reranker scores twenty token-bounded full
  chunks instead of 200-char snippets); the query-embedding cache eliminates
  repeat encodes (embedding phase mean 0.0001s in mixed scenarios); and every
  remaining slow scenario is bounded by exactly one component - the pure-Python
  local store engine's GIL-bound scans (qdrant phase mean 149s on the 6.3 GB
  collection) - with reranker batching second. Both successors are approved and
  in motion: the qdrant server-mode promotion (implementation dispatched, with
  provisioning research persisted) and the deferred reranker evaluation.
- Quality gate: 8/8 needle probes at 100% precision on the full reworked stack;
  the chunking integration tests separately prove the new capability (content
  past the old 8000-char horizon is retrievable with matched-passage snippets).
- Operator persona pass under live multi-agent saturation: status/jobs surfaces
  rendered the storm coherently; a peak-contention timeout produced the
  documented diagnostics and the suggested retry succeeded with full honest
  phase attribution in the JSON envelope.

Verification status: full unit suite green except one pre-existing failure owned
by the sibling operability feature's in-flight work; 51 GPU integration tests
green; quality 8/8; ruff, strict type-checking, and complexity gates clean on
every commit.
