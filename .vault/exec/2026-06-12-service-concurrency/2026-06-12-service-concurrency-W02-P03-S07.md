---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S07'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Rerank with token-bounded full candidate content instead of 200-char snippets and expose reranker max-length configuration

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Description

- Rerank on rerank_text (full candidate content) instead of the 200-char
  display snippet; cap input chars at ~6x the token bound to spare
  tokenizer work on oversized rows.
- Add the `reranker_max_length` knob (default 1024) and pass it to both
  CrossEncoder constructors (shared registry instance and searcher
  fallback).

## Outcome

The CrossEncoder now scores real content. Combined with chunking, rerank
inputs are the matched chunk, token-bounded by the model tokenizer.

## Notes
