# RAG Evaluation Frameworks

**Date**: 2026-03-08
**Task**: #8
**Status**: Complete

## Recommendation

**Keep raw pytest.** The existing `test_quality.py` is the right approach.

## Why Raw pytest Is Correct

1. **No generation = no LLM-as-judge needed** — this is a retrieval-only system
2. **Deterministic tests** — same query + corpus + model = same results
3. **Concrete assertions** — "security-audit in top 10" > "contextual precision = 0.73"
4. **Real hardware mandate** — already satisfied by existing GPU tests

## Frameworks Evaluated

### RAGAS — Wrong Fit

Evaluates LLM-generated answers (faithfulness, answer relevancy). This project has no generation component. Core value proposition is irrelevant. Retrieval metrics require LLM-as-judge — adds cost, non-determinism, API dependency.

### DeepEval — Marginal Benefit

pytest-compatible, but requires LLM-as-judge (OpenAI API), adds non-determinism, heavy dependency. Better than RAGAS for this use case but still overkill.

### LangSmith — Wrong Ecosystem

Cloud service, API key required, LangChain dependency.

## Optional Enhancement

Add MRR/NDCG/Precision@k as simple helper functions (15 lines, zero deps):

```python
def mrr(results, expected_ids):
    for i, r in enumerate(results, 1):
        if r.id in expected_ids:
            return 1.0 / i
    return 0.0

def precision_at_k(results, expected_ids, k):
    return sum(1 for r in results[:k] if r.id in expected_ids) / k
```
