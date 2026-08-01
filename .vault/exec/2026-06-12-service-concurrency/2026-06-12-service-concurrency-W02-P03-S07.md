---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-07-27'
body_hash: 'sha256:4ee1a92a772417034752a938049e6732b125b6a69748dde1c3da4c10019d1725'
step_id: 'S07'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Rerank with token-bounded full candidate content instead of 200-char snippets and expose reranker max-length configuration

## Description

### Scope

- `src/vaultspec_rag/search/_searcher.py`

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

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
