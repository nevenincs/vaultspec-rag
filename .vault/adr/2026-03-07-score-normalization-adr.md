---
tags:
  - "#adr"
  - "#gpu-rag-stack"
date: 2026-03-07
related:
  - "[[2026-03-07-continuous-research]]"
---

# ADR: Sigmoid + min-max per-source normalization in `search_all()`

## Status

Accepted

## Context

`search_all()` combines vault search results (graph-boosted RRF scores) with
codebase search results (CrossEncoder logit scores). These are on incompatible
scales:

- **RRF scores** (Qdrant, k=2): range ~[0.05, 0.7], rank-based
- **CrossEncoder logits** (ms-marco-MiniLM-L6-v2): range ~[-12, +12], unbounded

Sorting the combined list by raw score produces meaningless rankings.

## Decision

Normalize each source's scores independently before combining:

1. **CrossEncoder logits**: sigmoid normalization (`1/(1+exp(-x))`), maps
   unbounded logits to [0, 1].
2. **RRF scores**: min-max normalization (`(s-lo)/(hi-lo)`), maps to [0, 1].
3. **Weighted combination**: `final = w_vault * vault_norm + w_code * code_norm`,
   default weights 0.5/0.5.

Normalization is **per-result-set** (each source independently), not global.

## Rationale

1. **Per-source normalization** is industry standard. OpenSearch's hybrid search
   normalizes each sub-query independently using min-max before combining with
   weighted arithmetic mean (verified via their documentation and benchmarks).

2. **Sigmoid for CrossEncoder** is the natural transform: logits are the
   model's pre-activation output, sigmoid is the inverse logit. It preserves
   ranking order (monotonic) and has no parameters to tune.

3. **Min-max for RRF** works because RRF scores are bounded and have a
   meaningful distribution within each query. Edge cases are handled:
   empty list returns `[]`, single element returns `[1.0]`, all-same returns
   `[1.0, ...]`.

4. **Alternatives rejected:**
   - DBSF: only works within a single `query_points()` call, not cross-source
   - Rank-based RRF on both: loses CrossEncoder score magnitude information
   - Global normalization: one source's scale dominates the other

## Consequences

- `search.py` gains `_sigmoid()` and `_min_max()` helper functions.
- `search_all()` normalizes before combining, then sorts by normalized score.
- Weights are configurable (default 0.5/0.5), tunable via quality tests.
- CrossEncoder scores retain their magnitude signal (high-confidence matches
  score higher than marginal ones).
