---
name: rerankers-score-real-content
trigger: always_on
---

# Rerankers score real content

## Rule

Reranking inputs must be the token-bounded full candidate content, never a
fixed-character snippet or any other display proxy.

## Why

The `2026-06-12-service-concurrency-research` (finding F11) caught the
CrossEncoder scoring 200-character display snippets while the full content sat
in memory - the model's semantic capacity was discarded and ranking was biased
toward candidates whose opening characters echoed the query. The
`2026-06-12-service-concurrency-adr` made content reranking a decision: the
reranker's own tokenizer enforces the token bound, and the display snippet is a
rendering concern only.

## How

- Good: carry the candidate's full content on the result object
  (`rerank_text`), cap it at a generous multiple of the token bound to spare
  tokenizer work, and let the CrossEncoder's `max_length` do the exact
  truncation (`src/vaultspec_rag/search/_searcher.py`).
- Bad: passing `result.snippet`, a title, or any fixed-width prefix as the
  reranker's document side - it will pass every test while silently degrading
  ranking quality.
