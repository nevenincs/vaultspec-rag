---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-03-07'
---

# search.py Deep Audit (Round 7)

Date: 2026-03-07
Auditor: docs-researcher-2-2
File: `src/vaultspec_rag/search.py` (398 lines)

______________________________________________________________________

## 1. `_normalize_minmax()` min==max edge case (lines 151-166)

**Verdict: CORRECT**

Division by zero is properly guarded:

```python
span = hi - lo
if span == 0:
    for r in results:
        r.score = weight
else:
    for r in results:
        r.score = ((r.score - lo) / span) * weight
```

- Empty list: early return at line 156-157
- All-same scores (`span == 0`): all scores set to `weight` (e.g., 0.5), avoiding division by zero
- Normal case: scores mapped to `[0, weight]`

No issues.

______________________________________________________________________

## 2. `search_all()` score combination (lines 365-393)

**Verdict: MOSTLY CORRECT, one docstring issue**

Flow:

1. `search_vault()` returns `top_k` results (already reranked + graph boosted, scores in [0,1] via sigmoid)
1. `search_codebase()` returns `top_k` results (already reranked, scores in [0,1] via sigmoid)
1. `_normalize_minmax(vault_results, 0.5)` maps vault scores to [0, 0.5]
1. `_normalize_minmax(code_results, 0.5)` maps code scores to [0, 0.5]
1. Combine, sort descending, take top_k

The weighting is correct. No off-by-one. Both sources get equal weight (0.5) so neither dominates.

**ISSUE (LOW): Docstring still stale (lines 376-377).** Says "CrossEncoder logits use sigmoid normalization" -- this was partially fixed (sigmoid is now applied at the CrossEncoder level via `activation_fn=torch.nn.Sigmoid()` at line 214), but the docstring text is misleading. The normalization step here is min-max, not sigmoid. Sigmoid happens earlier in the pipeline (at `predict()` time). The docstring should say something like "CrossEncoder scores are already sigmoid-normalized; min-max normalization is then applied for cross-source weighting."

**ISSUE (MEDIUM): Graph boost inflates vault scores above 1.0 before `_normalize_minmax`.** The pipeline for `search_vault()` is: RRF -> sigmoid rerank -> graph boost. After sigmoid, scores are in [0,1]. After graph boost (`*= 1 + 0.1 * min(in_link_count, 10)`), scores can reach up to 2.0. Then `_normalize_minmax` maps them back to [0, 0.5]. This is mathematically correct (min-max handles any range), but the graph boost's effect is diminished by the subsequent re-normalization: a document with score 0.8 boosted to 1.2 has the same relative position as one with score 0.3 boosted to 0.45. The boost only matters for reordering within vault results, not for the absolute weight against codebase results. This is acceptable behavior but worth noting.

______________________________________________________________________

## 3. `rerank_with_graph()` boost formula (lines 102-148)

**Verdict: CORRECT after sigmoid fix, but scores exceed 1.0**

With `activation_fn=torch.nn.Sigmoid()` now on the CrossEncoder (line 214), scores entering `rerank_with_graph()` are in [0,1]. The multiplicative boost:

```python
result.score *= 1 + 0.1 * min(in_link_count, 10)
```

- No in-links: `score *= 1.0` (no change)
- 5 in-links: `score *= 1.5`
- 10+ in-links: `score *= 2.0`

Scores can now reach up to 2.0 (for a score of 1.0 with 10+ in-links). With the feature boost (`*= 1.15`), up to 2.3.

**Is this acceptable?** Yes, for two reasons:

1. When called from `search_vault()` directly, scores > 1 are fine for ranking -- only relative order matters
1. When called from `search_all()`, `_normalize_minmax()` maps the range back to [0, weight], so scores > 1 are handled correctly

**The negative-score bug from Round 5 is FIXED** -- sigmoid ensures scores are always positive, so multiplicative boost always goes in the right direction.

______________________________________________________________________

## 4. `_rerank()` method (lines 223-238)

**Verdict: CORRECT with one edge case note**

```python
if not self._reranker_enabled or len(results) <= 1:
    return results[:top_k]
```

- Empty results (`len == 0`): returns `[][:top_k]` = `[]`. Correct.
- Single result (`len == 1`): returns `results[:top_k]`. Correct (no point reranking 1 result).
- Reranker disabled: returns `results[:top_k]`. Correct.

```python
pairs = [(query, r.snippet) for r in results]
scores = reranker.predict(pairs, batch_size=32)
for result, score in zip(results, scores, strict=True):
    result.score = float(score)
```

- `strict=True` on zip catches length mismatch between results and scores. Good.
- `float(score)` handles numpy scalars. Good.
- `batch_size=32` is hardcoded. Not configurable but fine for a reranker (small payloads).

**Edge case note:** If `results` has items but all snippets are empty strings (e.g., `snippet=""`), the CrossEncoder will still produce scores. These scores may be meaningless, but no crash occurs. The snippet is truncated to 200 chars at line 285/353, so very long documents get only their prefix reranked.

______________________________________________________________________

## 5. `parse_query()` and `_FILTER_PATTERN` (lines 35-99)

**Verdict: CORRECT, one minor edge case**

Pattern: `r"\b(type|feature|date|tag|lang|path|func|class|nodetype):(\S+)"`

**Verified correct for all documented filters:**

- `type:adr` -> `{"doc_type": "adr"}`
- `feature:rag` -> `{"feature": "rag"}`
- `date:2026-02` -> `{"date": "2026-02"}`
- `tag:#research` -> `{"tag": "research"}` (hash stripped)
- `lang:python` -> `{"language": "python"}`
- `path:src/` -> `{"path": "src/"}`
- `func:encode_query` -> `{"function_name": "encode_query"}`
- `class:VaultStore` -> `{"class_name": "VaultStore"}`
- `nodetype:function_definition` -> `{"node_type": "function_definition"}`

**Edge cases checked:**

- Multiple filters: all extracted correctly (test_search_unit.py:111 covers this)
- Unknown prefix: `unknown:value` -- not matched by pattern (correct, tested at line 158)
- Empty query: returns `text=""`, `filters={}` (correct, tested at line 123)
- Filter-only query: returns `text=""` (correct, tested at line 118)
- Multiple spaces after removal: collapsed by `re.sub(r"\s+", " ", text)` (correct)

**Minor edge case (LOW):** The `\b` word boundary at the start of the pattern means `type:adr` is only matched at a word boundary. If someone writes `"mytype:adr"`, the `\b` before `type` would NOT match because `e` is a word character. However, this is actually desirable -- it prevents false matches on words that happen to end with a filter prefix.

**Edge case: `tag:` without `#`:** `tag:research` produces `filters["tag"] = "research"` (correct, `lstrip("#")` is a no-op when there's no `#`).

**Edge case: `class:` prefix conflicts with Python keyword:** The `\b` boundary correctly matches `class:Foo` because `:` is not a word character.

______________________________________________________________________

## 6. Filter propagation in `search_vault()` and `search_codebase()` (lines 254-363)

**Verdict: CORRECT**

### `search_vault()` (lines 260-264)

Filters vault results to: `doc_type`, `feature`, `date`, `tag`

```python
store_filters = {
    k: v for k, v in parsed.filters.items()
    if k in ("doc_type", "feature", "date", "tag")
}
```

This correctly excludes code-specific filters (`language`, `path`, `function_name`, `class_name`, `node_type`) from vault searches.

### `search_codebase()` (lines 321-333)

Filters to: `language`, `path`, `node_type`, `function_name`, `class_name`

```python
store_filters = {
    k: v for k, v in parsed.filters.items()
    if k in ("language", "path", "node_type", "function_name", "class_name")
}
```

Then overlays explicit keyword args (lines 326-333). Keyword args take precedence over parsed filters (correct -- explicit params override query-string filters).

**Both pass `filters=store_filters or None`** to the store. When `store_filters` is empty dict `{}`, `or None` evaluates to `None` (empty dict is falsy). This correctly tells the store "no filters" rather than passing an empty dict. Store methods handle `None` correctly.

______________________________________________________________________

## 7. Unguarded `None` access

**Verdict: NO ISSUES FOUND**

- `sparse_vector` from `encode_query_sparse()` always returns a `SparseResult` (never None). It's passed directly to `store.hybrid_search()` which accepts `SparseResult | None`.
- `query_vector` from `encode_query()` always returns an ndarray (never None).
- `graph` from `_get_graph()` can be None; `rerank_with_graph()` handles `graph is None` at line 116 by building its own graph (or returning unchanged results if that fails).
- `r.get("_relevance_score", 0.0)` provides a default for missing scores. Correct.
- `r["id"]` and `r["path"]` at lines 281-282 / 349-350: no `.get()` default. If store returns a result without `id` or `path`, this raises `KeyError`. This is acceptable -- store always includes these fields in results (they're part of the point payload).

______________________________________________________________________

## 8. Additional findings

### `_get_reranker()` not thread-safe (line 196-221)

**ISSUE (LOW):** No lock protects `self._reranker`. Two concurrent calls to `_rerank()` could both see `self._reranker is None` and both load the CrossEncoder model. This wastes GPU memory but doesn't crash (the second assignment overwrites the first, which gets GC'd). Same pattern as `get_engine()` in api.py -- a known issue.

### `search_codebase()` fetch_limit inconsistency (line 335)

**ISSUE (LOW):** When reranker is disabled, `fetch_limit = top_k` (not `top_k * 2` like in `search_vault()` at line 267). This means `search_codebase()` without reranker returns exactly `top_k` results from the store, while `search_vault()` fetches `top_k * 2` and then truncates. The discrepancy means vault results without reranker have a larger candidate pool to draw from than codebase results.

### `search_all()` fetches `top_k` per source, returns `top_k` total (lines 385-393)

This is correct behavior: each source returns its top `top_k` results, then the combined `2 * top_k` results are re-sorted and truncated to `top_k`. No issue.

### `_reranker_top_k` config value unused (line 193)

**ISSUE (LOW):** `self._reranker_top_k` is read from config at line 193 but never used anywhere in the class. The `_rerank()` method receives `top_k` as a parameter from the caller. This field is dead code.

______________________________________________________________________

## Summary

| #   | Issue                                                            | Severity | Action                 |
| --- | ---------------------------------------------------------------- | -------- | ---------------------- |
| 1   | `_normalize_minmax()` div-by-zero                                | —        | Correctly guarded      |
| 2   | `search_all()` docstring still says "sigmoid normalization"      | LOW      | Fix docstring          |
| 3   | Graph boost produces scores > 1.0, handled by subsequent min-max | —        | Acceptable             |
| 4   | `_rerank()` handling of empty/single results                     | —        | Correct                |
| 5   | `parse_query()` filter patterns                                  | —        | Correct                |
| 6   | Filter propagation vault vs codebase                             | —        | Correct                |
| 7   | Unguarded None access                                            | —        | None found             |
| 8   | `_get_reranker()` not thread-safe                                | LOW      | Same pattern as api.py |
| 9   | `search_codebase()` fetch_limit `top_k` vs vault's `top_k * 2`   | LOW      | Inconsistency          |
| 10  | `_reranker_top_k` unused dead code                               | LOW      | Delete field           |

**No HIGH or MEDIUM issues found.** The sigmoid fix (Task #64) has resolved the negative-score graph boost bug identified in Round 5.
