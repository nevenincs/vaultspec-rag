---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S05'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Group chunk hits per document in vault search with best-chunk scoring and matched-chunk snippets

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Description

- Group chunk-level vault hits to their best-scoring chunk per document
  after reranking; rerank a 2x top_k candidate set so grouping cannot
  under-fill the final page.
- Snippets now come from the matched chunk rather than the document head.
- Resolve relevance-feedback ids to the head-chunk point with a
  pre-chunking fallback probe.

## Outcome

Doc-level search contract preserved (no duplicate documents in results)
while snippets show the matched passage. The existing relevance-feedback
integration test passes against the chunked layout.

## Notes
