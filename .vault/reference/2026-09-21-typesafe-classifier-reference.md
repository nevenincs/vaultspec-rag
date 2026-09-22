---
tags:
  - '#reference'
  - '#typesafe-classifier'
date: '2026-09-21'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:0a850f83828693d8c8249f19019ba8f8ebca2ef7a4a8b564988a49557f7e4717'
related: []
---

# `typesafe-classifier` reference: search classification integration seams

Reviewed the searcher, store retrieval, result shaping, noise policy and public combined facade at the worktree baseline `0.4.32` on 2026-09-21. This record describes current behavior and integration constraints.

## Summary

### Retrieval and reranking

`src/vaultspec_rag/_store_search.py:40` defines the shared HybridSearchRequest. Dense and optional sparse lanes use per-prefetch filters and a prefetch limit four times the requested store limit. Fusion uses RRF with k=60; selected hybrid errors fall back to dense-only with the same filter (`src/vaultspec_rag/_store_search.py:263`). Feedback anchors alter the dense recommendation query and do not apply to documents.

`src/vaultspec_rag/search/_searcher.py:430` owns CrossEncoder reranking: sigmoid scores replace retrieval scores, full rerank_text supplies model input, and sorting precedes truncation. Disabled reranking or fewer than two candidates preserves retrieval scores. Query encoding is cached by surface and cleaned query; metadata tokens remain outside encoded text (`src/vaultspec_rag/search/_searcher.py:984`).

### Corpus-specific policies precede final truncation

Vault retrieval fetches max(4k,20) candidates with reranking or 2k without. It removes index records, maps full content, reranks all fetched chunks, groups by document, applies graph and intent weighting, caps document types, filters explicit statuses and truncates. Grouping and caps can remove useful candidates before a classifier placed solely at the public return boundary (`src/vaultspec_rag/search/_searcher.py:602`).

Code retrieval pushes domain filters into storage, applies path globs and missing-domain fallback, and widens on depletion. After reranking its complete surviving window, it applies domain demotion, preference nudges and locale deduplication (`src/vaultspec_rag/search/_searcher.py:748`, `src/vaultspec_rag/search/_searcher.py:828`). The cap can reach max(base\*4,500); widening must not accidentally multiply this work without a separate classifier budget.

Document retrieval uses the same ordinary fetch budget but truncates inside the reranker (`src/vaultspec_rag/search/_searcher.py:1125`). It retains native locator and document metadata.

### Combined surfaces currently differ

Direct VaultSearcher combined search encodes once, queries three domain pipelines, reranks merged candidates again and applies deterministic source/path/id tie breaks (`src/vaultspec_rag/search/_searcher.py:1198`). The public service facade instead counts and searches each domain independently under a lease, preserving failures and source facts (`src/vaultspec_rag/_public_search.py:336`). CombinedSearchOutcome selects the final page from successful domain results without that additional common rerank (`src/vaultspec_rag/search/_outcomes.py:161`). Classification must cover both paths and retain the public partial-outcome contract.

### Existing objects carry scoring evidence but not stored code domains

SearchResult and DocumentSearchResult retain rerank_text separately from the 200-character display snippet (`src/vaultspec_rag/search/_models.py:41`). Raw code rows contain domain metadata, but mapping drops it and later demotion reclassifies the path (`src/vaultspec_rag/search/_result_shaping.py:236`, `src/vaultspec_rag/search/_noise.py:131`). Explicit domain filtering must remain authoritative regardless of model predictions.

### Architectural coverage

Accepted `2026-06-30-search-noise-filtering-adr` and `2026-05-31-search-postprocess-adr` preserve CrossEncoder relevance authority; `2026-06-24-vault-pipeline-search-adr` rejects inferred intent for the existing prior. The requested hosted, confidence-gated mode is a distinct optional boundary that needs explicit scoped decision coverage. Existing local/GPU inference, per-prefetch filters, explicit service fallback and inactive classifier behavior retain their current authority. The classification research is `2026-09-21-typesafe-classifier-research`.

### Production-only filtering was erased before retrieval

The same \_clean helper normalized noise configuration and explicit only_domains through NOISE_DOMAINS, which deliberately excludes production. Both inline only:prod and programmatic only_domains=["prod"] therefore became an empty constraint before Qdrant and post-filtering. The minimal correction uses all DOMAINS only for the only set, preserving production-never-noise elsewhere. Evidence: src/vaultspec_rag/search/\_noise.py, \_clean and resolve_noise_policy; src/vaultspec_rag/search/\_searcher.py, \_fetch_codebase_candidates. Inline/programmatic and mixed-domain regression coverage is in src/vaultspec_rag/tests/test_typesafe_search.py and test_search_noise.py. This hard-filter defect is independent of hosted classification.
