---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S11'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Add per-surface Qwen3 query instructions for vault and codebase searches

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

- Add per-surface Qwen3 task instructions (documentation retrieval for
  vault, code retrieval for codebase) selected via encode_query surface
  argument; the generic built-in query prompt remains the fallback.
- Plumb the surface through `_encode_query` from both timed search paths.

## Outcome

Instruction-tuned query encoding active per surface; the prompt-name
regression test still passes for the fallback path.

## Notes
