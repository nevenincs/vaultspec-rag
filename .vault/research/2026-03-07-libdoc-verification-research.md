---
tags:
  - '#research'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-06-30'
---

# Library Documentation Verification Audit

Date: 2026-03-07

______________________________________________________________________

## Library: qdrant-client (Round 1)

**Verified:** 2026-03-07
**Sources:**

- <https://python-client.qdrant.tech/qdrant_client.qdrant_client>
- <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- <https://api.qdrant.tech/api-reference/search/query-points>

### API calls verified OK

- `QdrantClient(path=str(...))` — correct constructor for local mode (store.py:139)
- `client.collection_exists(name)` — correct (store.py:168)
- `client.create_collection(collection_name, vectors_config={...}, sparse_vectors_config={...})` — correct signature with named vector configs (store.py:171-182)
- `models.VectorParams(size=..., distance=models.Distance.COSINE)` — correct (store.py:174-176)
- `models.SparseVectorParams()` — correct, no modifier needed for SPLADE (store.py:180)
- `client.create_payload_index(collection_name, field_name, field_schema=models.PayloadSchemaType.KEYWORD)` — confirmed correct signature (store.py:199-203)
- `client.upsert(collection_name, points=[...])` — correct (store.py:268-271)
- `models.PointStruct(id=..., vector=..., payload=...)` — correct (store.py:251-266)
- `models.SparseVector(indices=..., values=...)` — correct (store.py:246-249)
- `client.delete(collection_name, points_selector=models.PointIdsList(points=[...]))` — confirmed correct (store.py:333-336)
- `client.scroll(collection_name, scroll_filter=..., limit=..., offset=..., with_payload=..., with_vectors=False)` — all param names confirmed correct (store.py:372-378)
- `models.Filter(must=[...])` — correct (store.py:399-406, 476-483)
- `models.FieldCondition(key=..., match=...)` — correct (store.py:401-404, 479-482)
- `models.MatchValue(value=...)` — correct for exact keyword match (store.py:685, 699)
- `models.MatchAny(any=[...])` — correct for multi-value match (store.py:403, 693)
- `models.MatchText(text=...)` — correct for full-text substring match (store.py:720)
- `models.Prefetch(query=..., using=..., limit=..., filter=...)` — confirmed: param is `filter`, NOT `query_filter` (store.py:540-545)
- `client.query_points(collection_name, prefetch=[...], query=models.FusionQuery(fusion=models.Fusion.RRF), limit=...)` — correct signature (store.py:562-567)
- `results.points` — correct, `query_points` returns object with `.points` attribute (store.py:568)
- `client.query_points(..., query=dense_vec, using="dense", limit=..., query_filter=...)` — correct for dense-only fallback; note `query_filter` is the correct param name on `query_points` itself (store.py:575-581)
- `client.retrieve(collection_name, ids=[...], with_payload=True, with_vectors=False)` — correct (store.py:448-453)
- `client.count(collection_name=...).count` — correct (store.py:430)
- `client.close()` — correct (store.py:147)

### API calls with discrepancies

None found. All qdrant-client API calls in store.py match the documented signatures.

### Notes

- The code correctly uses `filter=` on `Prefetch` objects and `query_filter=` on the top-level `query_points()` call. These are different parameter names by design in the qdrant-client API.
- `models.FusionQuery` is confirmed correct. Qdrant also offers `models.RrfQuery` with tunable `k` parameter as an alternative, but `FusionQuery(fusion=Fusion.RRF)` is the standard approach.
- The `_stable_id` hash approach (SHA-256 -> 8 bytes -> int) is a valid strategy for Qdrant local mode which requires integer or UUID point IDs.

______________________________________________________________________

## Library: sentence-transformers (Round 2)

**Verified:** 2026-03-07
**Sources:**

- <https://www.sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html>
- <https://www.sbert.net/docs/package_reference/sparse_encoder/SparseEncoder.html>
- <https://www.sbert.net/docs/package_reference/cross_encoder/cross_encoder.html>

### API calls verified OK

- `SentenceTransformer(model_name, model_kwargs={...}, tokenizer_kwargs={...})` — confirmed: constructor accepts `model_kwargs`, `tokenizer_kwargs`, and `config_kwargs` (embeddings.py:179-183)
- `model_kwargs={"torch_dtype": torch.float16}` — correct, passed through to `AutoModel.from_pretrained()` (embeddings.py:169-171)
- `model_kwargs={"attn_implementation": "flash_attention_2"}` — correct, `attn_implementation` is a valid kwarg for `AutoModel.from_pretrained()` and is correctly placed in `model_kwargs` (embeddings.py:175-176)
- `model.encode(texts, batch_size=..., show_progress_bar=..., normalize_embeddings=True)` — all params confirmed valid (embeddings.py:236-241)
- `model.encode([query], prompt_name="query", normalize_embeddings=True)` — `prompt_name` is confirmed valid parameter (embeddings.py:267-271)
- `SparseEncoder(model_name, device="cuda", model_kwargs={...})` — confirmed: constructor accepts `device` and `model_kwargs` (embeddings.py:186-189)
- `CrossEncoder(model_name, device="cuda")` — confirmed: `device` is a valid constructor parameter (architecture doc, not currently used in codebase)
- `reranker.predict(pairs)` — confirmed: returns numpy array of scores by default (architecture doc, not currently used in codebase)

### API calls with discrepancies

- **`self._sparse_model.encode(texts, batch_size=...)`** at embeddings.py:293-296 — **POTENTIAL ISSUE:** The SparseEncoder docs show three methods: `encode()`, `encode_query()`, and `encode_document()` (singular, NOT plural). The code uses generic `encode()` for both documents (line 293) and queries (line 319). This works but misses query-specific prompt optimization. The `encode_query()` method automatically applies a "query" prompt if the model defines one. Similarly, `encode_document()` applies a "document" prompt.

  **RECOMMENDATION (not a bug):** Consider using `encode_query()` for query encoding and `encode_document()` for document encoding to leverage SPLADE's query/document asymmetry. However, `encode()` still works correctly -- it just doesn't apply role-specific prompts.

  Note: The method is `encode_document` (singular), NOT `encode_documents` (plural). If switching, the batch loop would call `self._sparse_model.encode_document(texts, batch_size=...)`.

### Notes

- The `tokenizer_kwargs={"padding_side": "left"}` at embeddings.py:182 is correctly passed to the tokenizer. This is a valid configuration for Qwen models which benefit from left-padding.
- The flash_attn probe pattern (import check before adding to model_kwargs) at embeddings.py:173-177 is a good defensive practice.
- CrossEncoder is referenced in CLAUDE.md architecture section but not currently implemented in the codebase (no imports or usage found in search.py or elsewhere).

______________________________________________________________________

## Library: FastMCP / MCP SDK (Round 3)

**Verified:** 2026-03-07
**Sources:**

- <https://github.com/modelcontextprotocol/python-sdk>
- <https://github.com/modelcontextprotocol/python-sdk/issues/1839>

### API calls verified OK

- `FastMCP("VaultSpec Search")` — correct constructor, accepts name string (mcp_server.py:26)
- `@mcp.tool()` decorator on sync `def` — correct, FastMCP supports both sync and async tool functions (mcp_server.py:134, 152, 188, 201, 212, 230, 252)
- `@mcp.resource("vault://{doc_id}")` — correct resource decorator syntax (mcp_server.py:276)
- `@mcp.prompt()` — correct prompt decorator (mcp_server.py:291)
- `mcp.run()` — correct for stdio transport (mcp_server.py:308)
- Tool function return types using Pydantic BaseModel — correct, FastMCP serializes return values (mcp_server.py:135, 153, etc.)

### API calls with discrepancies

- **Sync tools block the event loop** — All 7 tool functions in mcp_server.py are synchronous `def` (not `async def`). In older versions of the MCP SDK, sync tools were called directly on the event loop, blocking it. This was fixed in PR #1909 (`anyio.to_thread.run_sync()` for sync functions). **FIX NEEDED:** Ensure the project pins `mcp>=` a version that includes PR #1909, OR convert tools to `async def` with `anyio.to_thread.run_sync()` wrapping the heavy calls. If running a recent SDK version (post-PR #1909), this is a non-issue.

### Notes

- The sync tool pattern is architecturally concerning regardless of SDK version: each tool call involves GPU inference (embedding) and Qdrant I/O. Even with thread-pool wrapping, these are heavyweight operations. Consider whether async wrappers would provide better concurrency for multi-tool MCP sessions.
- The `get_comp()` lazy initialization with `threading.Lock()` is correctly implemented for thread safety (mcp_server.py:42-82).

______________________________________________________________________

## Library: tree-sitter / tree-sitter-language-pack (Round 4)

**Verified:** 2026-03-07
**Sources:**

- <https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.Node.html> (py-tree-sitter 0.25.2)
- <https://pypi.org/project/tree-sitter-language-pack/>
- <https://github.com/Goldziher/tree-sitter-language-pack>

### API calls verified OK

- `get_parser(grammar)` from `tree_sitter_language_pack` — correct function name (indexer.py:310)
- `parser.parse(source_bytes)` — correct, accepts bytes (indexer.py:314)
- `tree.root_node` — correct property (indexer.py:315)
- `node.children` — confirmed: returns list of child Nodes (indexer.py:347, 403, 424)
- `node.type` — confirmed: returns string node type (indexer.py:348, 364, 426)
- `node.start_byte`, `node.end_byte` — confirmed properties (indexer.py:337, 363, 425)
- `node.start_point`, `node.end_point` — confirmed: returns (row, col) tuple; code correctly uses `[0]` for row and adds 1 for 1-based lines (indexer.py:397-398, 406-407, 463-464, 469)
- `node.child_by_field_name("name")` — confirmed: returns `Node | None` (singular child, not list) (indexer.py:333)
- Grammar name `"python"` — confirmed valid (indexer.py:158)
- Grammar name `"rust"` — confirmed valid (indexer.py:159)
- Grammar name `"javascript"` — confirmed valid (indexer.py:161)
- Grammar name `"typescript"` — confirmed valid (indexer.py:163)
- Grammar name `"tsx"` — confirmed valid (indexer.py:164)
- Grammar name `"go"` — confirmed valid (indexer.py:165)
- Grammar name `"java"` — confirmed valid (indexer.py:166)
- Grammar name `"c"` — confirmed valid (indexer.py:167)
- Grammar name `"cpp"` — confirmed valid (indexer.py:169)
- Grammar name `"csharp"` — confirmed valid (NOT `c_sharp`) (indexer.py:172)
- Grammar name `"ruby"` — confirmed valid (indexer.py:173)
- Grammar name `"bash"` — confirmed valid (indexer.py:174)
- Grammar name `"kotlin"` — confirmed valid (indexer.py:182)
- Grammar name `"toml"` — confirmed valid (indexer.py:178)
- Grammar name `"json"` — confirmed valid (indexer.py:179)
- Grammar name `"html"` — confirmed valid (indexer.py:180)
- Grammar name `"css"` — confirmed valid (indexer.py:181)
- Grammar name `"yaml"` — confirmed valid (indexer.py:176-177)

### API calls with discrepancies

None found. All tree-sitter and tree-sitter-language-pack API calls match documented interfaces.

### Notes

- The code uses `source_bytes[node.start_byte:node.end_byte].decode("utf-8")` to extract text rather than `node.text`. Both approaches work, but `node.text` returns `bytes | None` (the raw bytes), so the manual slice + decode is equivalent and arguably more explicit.
- The `child_by_field_name()` usage is correct -- it returns a single `Node | None`, not a list. The plural `children_by_field_name()` method exists for multiple matches but is not needed here.
- All grammar names in `LANGUAGE_MAP` are confirmed valid against the tree-sitter-language-pack's supported language list (165+ languages). Notably, `"csharp"` is correct (not `"c_sharp"`).

______________________________________________________________________

## Summary of Critical Findings

| #   | Library               | Severity | Issue                                                                                                                                                                        |
| --- | --------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | sentence-transformers | LOW      | `SparseEncoder.encode()` used for both queries and documents instead of role-specific `encode_query()` / `encode_document()`. Works but may miss SPLADE prompt optimization. |
| 2   | MCP SDK               | MEDIUM   | All MCP tools are sync `def`. Older SDK versions block the event loop. Ensure SDK version includes PR #1909 fix, or convert to async.                                        |
| 3   | CLAUDE.md             | INFO     | CrossEncoder reranker is specified in architecture but not implemented in codebase.                                                                                          |

No critical API signature mismatches found. All qdrant-client and tree-sitter calls are correct.

______________________________________________________________________

## SparseEncoder Deep Dive

**Verified:** 2026-03-07
**Sources:**

- <https://www.sbert.net/docs/package_reference/sparse_encoder/SparseEncoder.html>

### Q1: `encode_documents` (plural) vs `encode_document` (singular)?

**NO, `encode_documents` (plural) does NOT exist.** Only `encode_document` (singular) is a method on `SparseEncoder`. The three encoding methods are:

- `encode()` — generic, no role-specific prompt
- `encode_query()` — applies "query" prompt/task routing
- `encode_document()` — applies "document" prompt/task routing

### Q2: `batch_size` parameter?

Yes. All three methods accept `batch_size: int = 32`. They also accept `sentences: str | list[str] | ndarray`, so passing a list of strings does batch encoding in a single call.

### Q3: Return type?

All three return: `list[Tensor] | ndarray | Tensor | dict[str, Tensor] | list[dict[str, Tensor]]`

By default (`convert_to_tensor=True, convert_to_sparse_tensor=True`), returns a 2D sparse tensor of shape `[num_inputs, vocab_size]`.

### Q4: Difference between `encode_query` and `encode_document`?

Yes, they differ in prompt and task routing:

- `encode_query()` — uses a predefined "query" prompt if the model defines one in its `prompts` dict, and sets task to "query" for Router module routing.
- `encode_document()` — uses a predefined "document" prompt if available, and sets task to "document" for Router module routing.
- `encode()` — uses no default prompt, no task routing.

For SPLADE v3 (`naver/splade-v3`), this distinction matters because SPLADE is an asymmetric model where query and document representations are generated differently.

### Impact on codebase

In `embeddings.py`:

- Line 293: `self._sparse_model.encode(truncated, batch_size=...)` — used for documents. Should ideally be `self._sparse_model.encode_document(truncated, batch_size=...)`.
- Line 319: `self._sparse_model.encode([query[:max_chars]])` — used for queries. Should ideally be `self._sparse_model.encode_query([query[:max_chars]])`.

Current code works but may produce suboptimal sparse representations if SPLADE v3 defines asymmetric query/document prompts.

______________________________________________________________________

## Round 5: Score Normalization Audit

**Verified:** 2026-03-07
**Sources:**

- <https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2>
- <https://sbert.net/docs/cross_encoder/usage/usage.html>

### Code analyzed

- `search.py:151-166` — `_normalize_minmax()` function
- `search.py:219-234` — `_rerank()` method (CrossEncoder)
- `search.py:361-389` — `search_all()` method
- `search.py:102-148` — `rerank_with_graph()` function
- `search.py:250-291` — `search_vault()` method

### Finding 1 (MEDIUM): Docstring claims sigmoid normalization, but none exists

The `search_all()` docstring (lines 373-374) states:

> "CrossEncoder logits use sigmoid normalization"

**No sigmoid normalization exists anywhere in search.py.** The actual pipeline is:

1. `search_vault()` / `search_codebase()` fetch RRF-fused results from Qdrant
1. `_rerank()` replaces scores with **raw CrossEncoder logits** via `result.score = float(score)` (line 232) — no sigmoid
1. `search_all()` applies `_normalize_minmax()` on the already-reranked results

The ms-marco-MiniLM-L6-v2 model outputs **raw logits** (unbounded, can be negative). The official HuggingFace model card recommends using `CrossEncoder(..., activation_fn=torch.nn.Sigmoid())` to normalize outputs to [0,1].

**Impact:** `_normalize_minmax()` still maps scores to [0,1], so final ranking is correct. However, min-max is sensitive to outliers — a single extreme logit compresses all other scores. Sigmoid produces more uniformly distributed scores.

**FIX OPTIONS:**

- Option A (preferred): Add `activation_fn=torch.nn.Sigmoid()` to the `CrossEncoder()` constructor at line 211
- Option B: Apply sigmoid post-hoc: `scores = 1 / (1 + np.exp(-scores))`
- Either way, fix the docstring to match implementation

### Finding 2: `_normalize_minmax()` is correctly implemented

Formula at line 166:

```python
r.score = ((r.score - lo) / span) * weight
```

Correctly implements `(x - min) / (max - min) * weight`.

Edge cases:

- Empty list: early return (line 156-157) — correct
- All-same scores (`span == 0`): all set to `weight` (line 162-163) — correct, avoids division by zero

### Finding 3 (HIGH): Graph multiplicative boost breaks on negative CrossEncoder logits

The score pipeline for `search_vault()` (lines 250-291) is:

```
RRF scores → _rerank() [CrossEncoder logits] → rerank_with_graph() → return
```

The graph boost at line 131:

```python
result.score *= 1 + 0.1 * min(in_link_count, 10)
```

This is a **multiplicative** boost ranging from 1.0x to 2.0x. With CrossEncoder logits:

- **Negative logits get penalized instead of boosted.** Example: a document with CrossEncoder score `-2.0` and 5 in-links gets `score = -2.0 * 1.5 = -3.0` — pushed further negative (penalized), which is the **opposite** of the intended boost.

- The feature neighbor boost at line 143 (`result.score *= 1.15`) has the **same sign problem**.

- With RRF scores (reranker disabled), this is fine — RRF scores are always positive.

**FIX NEEDED:** The multiplicative boost assumes non-negative scores. Options:

1. Apply sigmoid before graph reranking to ensure [0,1] scores
1. Switch to additive boost: `result.score += 0.1 * min(in_link_count, 10)`
1. Move graph reranking after min-max normalization (when scores are guaranteed [0,1])

### Finding 4: Weight application in `search_all()` is correct

```python
_normalize_minmax(vault_results, vault_weight)   # default 0.5
_normalize_minmax(code_results, code_weight)      # default 0.5
```

After normalization, vault scores are in [0, 0.5] and code scores are in [0, 0.5]. Combined and sorted correctly. Equal weighting prevents one source from dominating the other.

### Finding 5 (INFO): Score scales differ between direct and combined search

When called independently (not via `search_all()`):

- Reranker enabled: scores are raw CrossEncoder logits (roughly -5 to +12)
- Reranker disabled: scores are RRF fusion scores (always positive, typically 0 to ~0.03)

Not a bug — `_relevance_score` is for ranking, not comparison — but callers should not compare scores across `search_vault()` and `search_codebase()` without normalization.

### Summary

| #   | Issue                                                              | Severity | Action                                                         |
| --- | ------------------------------------------------------------------ | -------- | -------------------------------------------------------------- |
| 1   | Docstring claims sigmoid but none exists                           | MEDIUM   | Add `activation_fn=Sigmoid()` to CrossEncoder or fix docstring |
| 2   | `_normalize_minmax()` formula and edge cases                       | —        | Correct, no action needed                                      |
| 3   | Graph multiplicative boost inverts on negative CrossEncoder logits | **HIGH** | Fix: sigmoid before graph, or switch to additive boost         |
| 4   | Weight application in `search_all()`                               | —        | Correct, no action needed                                      |
| 5   | Inconsistent score scales across search methods                    | LOW      | Informational                                                  |

______________________________________________________________________

## Round 6: Qdrant Index Types and RRF Tuning

### Area 1: Qdrant Payload Index Types

#### Index type semantics

| Index Type | Supported Conditions                                           | Notes                                                                                                                      |
| ---------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| KEYWORD    | `MatchValue`, `MatchAny`, `MatchExceptValue`, `MatchExceptAny` | Exact match on string tokens. No range, no prefix, no full-text search.                                                    |
| INTEGER    | `Match` (exact), `Range` (gte/lte/gt/lt)                       | For numeric fields. Range filter uses `models.Range(gte=start, lte=end)`.                                                  |
| TEXT       | `MatchText` (full-text search with tokenization)               | Required for `MatchText` to perform tokenized search. Without a TEXT index, `MatchText` degrades to exact substring match. |
| FLOAT      | `Range`                                                        | For floating-point fields.                                                                                                 |
| BOOL       | `MatchValue`                                                   | For boolean fields.                                                                                                        |

#### Current codebase index configuration (store.py)

**Vault collection** (`ensure_table`, lines 192-203):

- `doc_type`: KEYWORD — correct. Used with `MatchValue`.
- `feature`: KEYWORD — correct. Used with `MatchValue`.
- `date`: KEYWORD — correct for current usage (`MatchValue` exact match after R22b-M1 fix). Cannot do range/prefix queries on dates. If date range filtering is needed in the future, would need INTEGER index on epoch timestamps or a different schema.
- `tags`: KEYWORD — correct. Used with `MatchAny`.

**Code collection** (`ensure_code_table`, lines 215-229):

- `language`: KEYWORD — correct. Used with `MatchValue`.
- `path`: KEYWORD — correct for exact match. Note: users writing `path:src/` in search queries expect prefix matching, but KEYWORD + `MatchValue` does exact equality only (R21-m4).
- `node_type`: KEYWORD — correct.
- `function_name`: KEYWORD — correct.
- `class_name`: KEYWORD — correct.
- `line_start`: INTEGER — correct. Enables `Range` conditions for line number filtering.

**Verdict:** All payload index types are correct for their current filter operations. No mismatches found.

#### Filtering without an index

Qdrant documentation confirms: filtering works without a payload index but triggers a full scan of all points. The index is an optimization, not a requirement. Fields used in `_build_filter` / `_build_code_filter` that lack indexes (e.g., `chunk_id`, `doc_id` when used in delete-by-filter) will work but scan all points. This is acceptable for infrequent operations like deletes.

### Area 2: RRF k Parameter

#### FusionQuery default k value

From Qdrant official documentation (hybrid search page):

> "k is a constant set to **2** by default"

The `FusionQuery(fusion=Fusion.RRF)` API does NOT accept a `k` parameter — it uses the hardcoded default of k=2.

#### RrfQuery API (since v1.16.0)

Qdrant v1.16.0 introduced `RrfQuery` which allows specifying the k constant:

```python
from qdrant_client.models import RrfQuery, Rrf

# Explicit k parameter
query = models.RrfQuery(rrf=models.Rrf(k=60))
```

This is a separate query type from `FusionQuery`. The `FusionQuery` remains available but does not expose `k`.

#### k=2 vs k=60: impact on ranking

The RRF formula is: `score = sum(1 / (k + rank_i))` across all retrieval methods.

| k value | Top-1 score  | Top-10 score | Ratio (top-1 / top-10) | Effect               |
| ------- | ------------ | ------------ | ---------------------- | -------------------- |
| k=2     | 1/3 = 0.333  | 1/12 = 0.083 | 4.0x                   | Heavy top-rank bias  |
| k=60    | 1/61 = 0.016 | 1/70 = 0.014 | 1.14x                  | Flatter distribution |

With k=2, the rank-1 result from one retriever gets 4x the score of the rank-10 result. With k=60 (standard from Cormack, Grossman & Hazell, 2009), the difference between rank 1 and rank 10 is only ~14%.

**k=2 biases heavily toward whichever retriever's top result happens to rank first**, potentially ignoring strong consensus at lower ranks. k=60 gives more credit to results that appear across multiple retrievers, even at moderate ranks.

#### Current codebase usage

`store.py` uses `FusionQuery(fusion=Fusion.RRF)` in both `hybrid_search` and `hybrid_search_codebase`. This gets the k=2 default. The k parameter cannot be changed without switching to `RrfQuery`.

**Impact:** With only 2 retrievers (dense + sparse), the effect is somewhat muted compared to multi-retriever scenarios. However, k=2 still means that if the dense retriever ranks document A at position 1 and the sparse retriever ranks it at position 5, A gets score `1/3 + 1/7 = 0.476`. If document B is ranked 2 by dense and 1 by sparse, B gets `1/4 + 1/3 = 0.583`. The spread between A and B is significant. With k=60, A gets `1/61 + 1/65 = 0.0318` vs B's `1/62 + 1/61 = 0.0325` — much closer, letting downstream reranking (CrossEncoder) make the final determination.

#### Recommendation

Switch from `FusionQuery(fusion=Fusion.RRF)` to `RrfQuery(rrf=Rrf(k=60))` for more balanced rank fusion that defers final ranking to the CrossEncoder reranker. This requires qdrant-client >= 1.16.0.

### Summary

| #   | Issue                                                 | Severity   | Action                                                        |
| --- | ----------------------------------------------------- | ---------- | ------------------------------------------------------------- |
| 1   | All payload index types match their filter operations | —          | No action needed                                              |
| 2   | KEYWORD index on `date` prevents future range queries | LOW        | Informational; redesign if date ranges needed                 |
| 3   | KEYWORD index on `path` does exact match, not prefix  | LOW        | Already noted in R21-m4                                       |
| 4   | `FusionQuery` uses RRF k=2 (not k=60)                 | **MEDIUM** | Switch to `RrfQuery(rrf=Rrf(k=60))` for standard RRF behavior |
| 5   | `RrfQuery` available since qdrant-client 1.16.0       | —          | Verify installed version before switching                     |

______________________________________________________________________

## Round 7: Code Chunking Strategy Research

### Current approach

Our `CodebaseIndexer` uses tree-sitter AST parsing to chunk code at function and class level boundaries (`_chunk_with_ast` in `indexer.py`). When AST parsing fails (unsupported language, parse errors), it falls back to `TextSplitter` with fixed-size character-based splitting and overlap.

### Literature review

#### cAST: AST-based structural chunking (EMNLP 2025 Findings)

The most relevant recent work is **cAST** (arXiv:2506.15655, accepted at EMNLP 2025 Findings). Key findings:

- **Approach:** Recursive greedy AST node merging — start from top-level AST nodes, greedily merge into chunks up to a size budget, recursively decompose nodes that exceed the budget. Preserves function/class boundaries as complete units.
- **Chunk size metric:** Non-whitespace character count (not tokens or lines) for cross-language comparability. Context windows tested: 4000 chars for RepoEval/SWE-Bench, 10000 chars for CrossCodeEval.
- **No overlap:** Chunks are non-overlapping and concatenate to reproduce the original file verbatim.
- **Results at Recall@5 / Precision@5:**
  - RepoEval: +1.8-4.3 Recall@5, +1.2-3.3 Precision@5 over fixed-size baselines
  - SWE-Bench: +0.7-1.1 Recall@5
  - Generation (Pass@1): up to +5.5 points on RepoEval with StarCoder2-7B
- **Key insight:** "Higher precision tends to convert into better generation performance" — ensuring top-k context is highly relevant reduces noise for downstream tasks.

**Comparison with our approach:** Our `_chunk_with_ast` already does function/class-level AST chunking, which is conceptually similar to cAST. The main difference is that cAST uses a **recursive greedy merging** strategy that can combine multiple small AST nodes (e.g., sequential import statements, small helper functions) into a single chunk up to a size budget, whereas our approach extracts each function/class as its own chunk regardless of size. This means we may produce many very small chunks (one-line helpers, constants) and some very large chunks (large classes), while cAST would merge the small ones and recursively split the large ones.

#### code-chunk library (supermemory.ai)

Practical AST-aware chunking library. Benchmark results:

- AST-based: **70.1% Recall@5, 0.43 IoU**
- Fixed-size baseline: **42.4% Recall@5, 0.34 IoU**
- Supports optional overlap via `overlapLines` parameter
- Recursive decomposition for functions exceeding max chunk size

#### General chunking research (Chroma, NVIDIA, Firecrawl)

- Chroma's 2024 evaluation (text-only, no code): recursive splitting at 200-400 tokens achieves 85-90% recall; semantic chunking reaches 91-92%.
- NVIDIA 2024 benchmark: page-level chunking won at 0.648 accuracy (document retrieval, not code).
- Firecrawl recommendation for code: recursive character splitting with code-aware separators (`\n\nclass`, `\n\ndef`), prioritizing keeping functions and classes intact.
- General consensus: 10-20% overlap helps for text; no evidence it helps for AST-aware code chunks.

### Qwen3-Embedding model guidance

- **Max context:** 32,768 tokens native. Performance degrades beyond 32K.
- **Practical recommendation:** Keep chunks under 16K tokens for optimal performance (Qwen3-Embedding-0.6B chunking analysis).
- **No code-specific chunking guidance** in the model card or documentation.
- The model explicitly supports code retrieval ("robust multilingual, cross-lingual, and code retrieval capabilities").
- Custom instruction prompts can improve code retrieval by 1-5% (e.g., `Instruct: Given a code search query, retrieve relevant code snippets`).
- Our current `max_embed_chars = 8000` config default is well within the 16K-token safe zone (roughly 2K-4K tokens depending on language).

### Comparison with our current implementation

| Aspect            | Our approach                                                     | cAST / literature best practice                       |
| ----------------- | ---------------------------------------------------------------- | ----------------------------------------------------- |
| Chunk granularity | Each function/class = 1 chunk                                    | Greedy merge small nodes, recursive split large nodes |
| Small nodes       | Each becomes its own chunk (imports, constants, one-liners)      | Merged into larger chunks up to size budget           |
| Large nodes       | Entire class as one chunk (can be very large)                    | Recursively decomposed at AST sub-boundaries          |
| Overlap           | TextSplitter fallback uses overlap                               | No overlap (AST boundaries are semantically complete) |
| Size budget       | No explicit max (limited by `max_embed_chars` at embedding time) | Explicit character budget per chunk                   |
| Chunk metadata    | file path, language, line numbers, function/class names          | Similar metadata preserved                            |

### Recommendations

1. **LOW priority — Merge small AST nodes:** Our approach creates separate chunks for every function/constant/import block. Merging consecutive small top-level nodes (e.g., imports + module docstring + small helpers) into a single chunk up to a size budget (~2000-4000 non-whitespace chars) would reduce chunk count and improve embedding quality for small code fragments that lack standalone semantic meaning. The cAST paper shows this improves Precision@5 by 1-3 points.

1. **LOW priority — Recursive decomposition of large nodes:** When a class exceeds the size budget, recursively chunk at method boundaries rather than embedding the entire class as one oversized chunk. Our `max_embed_chars` truncation at embedding time already prevents excessively long inputs, but truncation loses information. Recursive decomposition would preserve all content.

1. **NO ACTION — Overlap for AST chunks:** The literature does not support overlap for AST-aware chunks. Our current AST chunking (no overlap) is correct. The `TextSplitter` overlap in the fallback path is acceptable for non-AST text.

1. **NO ACTION — Overall strategy:** Function/class-level AST chunking is validated as the correct approach by recent research. The 70.1% vs 42.4% Recall@5 comparison (AST vs fixed-size) confirms that our AST-based approach is fundamentally sound. The potential improvements (items 1-2) are incremental optimizations, not architectural changes.

### Sources

- cAST paper: arXiv:2506.15655 (EMNLP 2025 Findings)
- code-chunk library: supermemory.ai/blog/building-code-chunk-ast-aware-code-chunking
- Chroma chunking evaluation: research.trychroma.com/evaluating-chunking
- Qwen3-Embedding-0.6B chunking analysis: x22x22.github.io/qwen3_embedding_analysis.html
- Qwen3-Embedding-8B model card: huggingface.co/Qwen/Qwen3-Embedding-8B

### Summary

| #   | Finding                                                              | Severity | Action                                                     |
| --- | -------------------------------------------------------------------- | -------- | ---------------------------------------------------------- |
| 1   | Function/class-level AST chunking is validated by literature         | —        | No change needed; our approach is correct                  |
| 2   | Small AST nodes (imports, constants) create low-quality chunks       | LOW      | Consider merging small consecutive nodes up to size budget |
| 3   | Large classes may exceed embedding context or get truncated          | LOW      | Consider recursive decomposition at method boundaries      |
| 4   | No overlap needed for AST chunks                                     | —        | Current behavior is correct                                |
| 5   | Qwen3-Embedding has no code-specific chunking guidance               | —        | Informational                                              |
| 6   | `max_embed_chars=8000` is safely within model's 16K-token sweet spot | —        | No change needed                                           |

______________________________________________________________________

## Round 8: VaultGraph Boost Calibration

### Current implementation

After CrossEncoder reranking (which now outputs sigmoid-normalized [0,1] scores), `rerank_with_graph()` in `search.py:102-148` applies two multiplicative boosts:

1. **In-link boost:** `score *= 1 + 0.1 * min(in_link_count, 10)` — ranges from 1.0x (0 links) to 2.0x (10+ links)
1. **Feature neighbor boost:** `score *= 1.15` — if any neighbor has the queried feature tag

These boosts apply to the already-truncated `top_k` results (line 292 truncates via `_rerank`, line 294 applies graph boost). The boosted scores are the final scores returned by `search_vault()`.

### Test-project in-link distribution (391 nodes)

| In-links | Nodes | Percentage | Boost factor  |
| -------- | ----- | ---------- | ------------- |
| 0        | 275   | 70.3%      | 1.0x          |
| 1        | 17    | 4.3%       | 1.1x          |
| 2        | 55    | 14.1%      | 1.2x          |
| 3        | 8     | 2.0%       | 1.3x          |
| 4        | 13    | 3.3%       | 1.4x          |
| 5-9      | 12    | 3.1%       | 1.5x-1.9x     |
| 10+      | 11    | 2.8%       | 2.0x (capped) |
| **Mean** | —     | —          | **1.13x**     |

Key observations:

- **70% of documents get no boost at all** (0 in-links)
- **94% get 1.4x or less** (0-4 in-links)
- Only **2.8% hit the 2.0x cap** (10+ links)
- Top hotspot has 77 in-links but is capped at the same 2.0x as a doc with 10 links

### Analysis: Is 2.0x max boost appropriate?

#### Scenario analysis with sigmoid [0,1] scores

| Scenario                        | Base score   | Links  | Boosted score  | Problem?                   |
| ------------------------------- | ------------ | ------ | -------------- | -------------------------- |
| Strong match, no links          | 0.90         | 0      | 0.900          | —                          |
| Moderate match, 10+ links       | 0.50         | 10     | 1.000          | Overtakes strong match     |
| Weak match, 10+ links + feature | 0.50         | 10     | 1.150          | 28% above strong match     |
| Strong match, 2 links           | 0.90         | 2      | 1.080          | Acceptable nudge           |
| Two matches, 2 vs 0 links       | 0.85 vs 0.80 | 2 vs 0 | 1.020 vs 0.800 | Link-heavy doc jumps ahead |

**The 2.0x cap can cause a moderately relevant hub document (score 0.50) to outrank a highly relevant document (score 0.90) with no links.** This is the core calibration concern.

However, this extreme case requires a 10+ link hub document to appear in the top-k results AND have a mediocre CrossEncoder score. In practice:

- The CrossEncoder already filtered to top-k before graph boost
- Only 2.8% of documents have 10+ links
- A hub doc with a 0.50 CrossEncoder score is unlikely to be in top-5

#### Typical case

For the **94% of documents with 0-4 links**, the boost ranges from 1.0x-1.4x. With sigmoid [0,1] scores, a 1.4x boost on a 0.7 score gives 0.98 — a significant but not extreme advantage. The practical effect is that documents with 2-3 in-links get a 20-30% score bump, which acts as a meaningful tie-breaker between similarly-scored results.

#### Feature boost stacking

The 1.15x feature neighbor boost stacks multiplicatively with the in-link boost. Maximum combined boost: 2.0 * 1.15 = 2.3x. This stacking amplifies the overtake risk for highly-connected feature-tagged documents.

### Literature context

IR literature on combining link-based and content-based scores:

- **Multiplicative boosting** is generally preferred over additive when the boost should have proportional impact (Solr/Elasticsearch best practices). Our multiplicative approach is correct in principle.
- **Calibration concern:** Multiplicative boosts are sensitive to magnitude. A 2x factor on [0,1] scores is large — it can double a score. In web search, PageRank is typically used as a log-scale feature in a learned ranking model, not as a raw multiplicative factor.
- **Additive approach:** Using `score += 0.05 * min(in_link_count, 10)` would cap the maximum additive boost at +0.5, acting as a tie-breaker on the [0,1] scale without allowing hub documents to dominate purely on link count.

### Recommendations

1. **LOW priority — Reduce the coefficient from 0.1 to 0.05:** `score *= 1 + 0.05 * min(in_link_count, 10)` would give a max boost of 1.5x instead of 2.0x. This reduces the overtake risk while preserving the link signal as a meaningful tie-breaker. A 0.50-score doc with 10 links would get 0.75 — still below a 0.80-score doc with 0 links.

1. **LOW priority — Consider log-dampening:** `score *= 1 + 0.1 * log2(1 + min(in_link_count, 10))` would give diminishing returns: 1 link = 1.1x, 2 links = 1.16x, 5 links = 1.26x, 10 links = 1.35x. This matches the intuition that the first few links are more informative than additional ones.

1. **NO ACTION — Feature boost magnitude:** The 1.15x feature neighbor boost is a reasonable magnitude for a binary signal. It's within the same range as 1-2 in-links. No change needed.

1. **NO ACTION — Overall approach:** Multiplicative boosting after CrossEncoder reranking is the correct pattern. The graph boost acts as a secondary signal on top of semantic relevance, which is the right hierarchy.

### Summary

| #   | Finding                                                                             | Severity | Action                                               |
| --- | ----------------------------------------------------------------------------------- | -------- | ---------------------------------------------------- |
| 1   | 2.0x max boost can cause hub docs (score 0.5) to outrank strong matches (score 0.9) | LOW      | Reduce coefficient from 0.1 to 0.05 (max 1.5x)       |
| 2   | Feature boost stacking reaches 2.3x combined maximum                                | LOW      | Acceptable, but depends on item 1                    |
| 3   | 70% of docs get no boost; typical boost is 1.0x-1.2x                                | —        | Well-calibrated for the common case                  |
| 4   | Cap at 10 links is reasonable (only 2.8% of docs exceed it)                         | —        | No change needed                                     |
| 5   | Multiplicative boosting is correct approach per IR literature                       | —        | No change needed                                     |
| 6   | Log-dampening is an alternative to reducing coefficient                             | LOW      | Optional; diminishing returns matches link semantics |
