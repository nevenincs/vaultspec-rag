---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-03-07'
---

# Round 21 Audit -- search.py, cli.py, mcp_server.py

## search.py

### R21-M1: `search_all` mixes incomparable scores after reranking (Major)

`search_all()` at line 343 calls `search_vault()` and `search_codebase()` independently, then sorts all results by score. When the CrossEncoder reranker is enabled, vault results have CrossEncoder scores (typically -10 to +10 range) *plus* graph boost multipliers, while codebase results have only CrossEncoder scores. Even without the reranker, RRF scores from different collections are not directly comparable because they depend on each collection's candidate pool. Sorting mixed scores as if they are on the same scale produces unreliable ranking.

**File:** `search.py:343-350`

### R21-M2: `_FILTER_PATTERN` regex does not match `tag:#research` correctly (Major)

The regex `\b(type|feature|date|tag|lang|path|func|class|nodetype):(\S+)` uses `\b` word boundary before the key. For `tag:#research`, `\b` requires a transition from non-word to word character. This works. However, the `(\S+)` capture group for `tag:#research` captures `#research` (the `#` is non-whitespace). Then line 90 does `value.lstrip("#")` to strip it. This is correct but fragile -- if a user writes `tag:research` (no `#`), it also works. The real issue: if any filter value contains whitespace-adjacent punctuation like `path:src/foo bar`, only `src/foo` is captured, silently dropping `bar`. This is a design limitation, not a bug per se, but there is no warning or documentation about it.

**File:** `search.py:35-37, 89-90`
**Severity downgrade:** Minor (the `\S+` behavior is typical for token-based query parsers)

### R21-M3: Graph rerank runs after CrossEncoder rerank, potentially undoing reranker ordering (Major)

In `search_vault()` at line 271-273, the CrossEncoder reranker runs first (`_rerank`), then graph reranking (`rerank_with_graph`) applies multiplicative boosts to the CrossEncoder scores and re-sorts. This means the graph boost can shuffle results that the CrossEncoder ranked precisely. The graph boost formula `score *= 1 + 0.1 * min(in_link_count, 10)` can multiply the score by up to 2x, which is a large perturbation on CrossEncoder logit scores. This may be intentional design, but worth noting as a quality concern.

**File:** `search.py:271-273, 131`

### R21-m1: `rerank_with_graph` accepts `root_dir` but also receives `graph` (Minor)

When `graph` is passed (as in line 273), the `root_dir` parameter is unused. The function signature requires `root_dir` even when not needed, coupling the caller to provide it unnecessarily. Not a bug, but a code smell.

**File:** `search.py:102-107`

### R21-m2: `_get_graph` error log says "Search failed" but it is a graph build failure (Minor)

Line 227 logs `"Search failed: %s"` but the actual error is graph construction. The existing `rerank_with_graph` function (line 122) correctly logs `"Graph build failed"`. The `_get_graph` method should match.

**File:** `search.py:227`

### R21-m3: `search_vault` does not propagate `tag` filter to store (Minor)

In `search_vault()` line 238-242, the store filter whitelist is `("doc_type", "feature", "date", "tag")`. The `parse_query` function stores tag filters under the key `"tag"` (line 90). However, `store._build_filter` handles `key == "tag"` by mapping it to the `"tags"` payload field (store.py line 664-669). This actually works correctly end-to-end, but the naming mismatch (`"tag"` in filters dict vs `"tags"` in Qdrant payload) is confusing and fragile. If someone changes the store filter builder without understanding this mapping, it will break.

**File:** `search.py:238-242`, `store.py:664-669`

### R21-m4: `search_codebase` does not pass `path` filter from inline query parsing (Minor)

The `search_codebase` method at line 299-303 whitelists `("language", "path", "node_type", "function_name", "class_name")` from parsed filters. The `_FILTER_KEY_MAP` maps `"path"` to `"path"` (line 45). This works, but the `path` filter from query parsing uses `MatchValue` (exact match) in the store's `_build_code_filter` (store.py line 693-699). A user writing `path:src/` likely expects prefix matching, not exact equality. This is a usability bug.

**File:** `search.py:299-303`, `store.py:693-699`

### R21-m5: Docstring claims "graph-aware re-ranking" but module does not implement full graph re-ranking (Minor)

The module docstring (line 3) says "graph-aware re-ranking" but `rerank_with_graph` only does simple in-link count boosting and neighbor feature matching. This is a minor docstring accuracy issue.

**File:** `search.py:3`

## cli.py

### R21-M4: `handle_search` creates new `VaultStore` and `EmbeddingModel` per invocation (Major)

Every `search` command (line 289-294) instantiates a fresh `VaultStore` and `EmbeddingModel`. The `EmbeddingModel` loads two GPU models (SentenceTransformer + SPLADE). For a CLI this is unavoidable (single invocation), so this is actually not a bug -- just an inherent latency cost. Downgrading.

**Severity downgrade:** Not a bug. Removed.

### R21-M5: `handle_test` uses `subprocess.call` and `raise SystemExit` (Minor)

Line 466: `raise SystemExit(subprocess.call(cmd))`. Using `subprocess.call` rather than `subprocess.run` is fine, but `raise SystemExit` bypasses Typer's exit handling. This works in practice but is unconventional for a Typer app. A `raise typer.Exit(code=result)` would be more idiomatic, though `SystemExit` is functionally equivalent.

**File:** `cli.py:466`

### R21-m6: Import ordering: `sys` import not grouped with stdlib (Minor)

Line 10 imports `sys` separately from the other stdlib imports on lines 5-8 (`os`, `shutil`, `Path`, `Annotated`, `Literal`). This is a style/lint issue.

**File:** `cli.py:5-10`

### R21-m7: `_handle_gpu_error` catches broad "CUDA" string match (Minor)

Line 43 checks `"CUDA" in str(exc) or "cuda" in str(exc)`. This is a heuristic that could match unrelated exceptions mentioning CUDA. Not likely to cause issues in practice, but a more targeted approach would check `isinstance(exc, RuntimeError)` first.

**File:** `cli.py:43`

### R21-m8: `main` callback skips workspace resolution for "test" and "server" (Minor)

Line 131: `if ctx.invoked_subcommand in ("test", "server"): return`. This means `--target` is silently ignored when running `vaultspec-rag --target /foo test`. The user gets no warning that their `--target` flag was not used.

**File:** `cli.py:131-132`

### R21-m9: `configure_logging` ignores `verbose` when `debug` is also set (Minor)

Line 125: `configure_logging(debug=debug, level="INFO" if verbose else None)`. If both `--debug` and `--verbose` are passed, behavior depends on `configure_logging` internals. The CLI does not enforce mutual exclusivity or document precedence.

**File:** `cli.py:125`

## mcp_server.py

### R21-C1: `get_code_file` path traversal check is bypassable on Windows (Critical)

Line 202-203:

```python
full_path = (comp.root_dir / path).resolve()
if not full_path.is_relative_to(comp.root_dir.resolve()):
```

On Windows, `Path.resolve()` normalizes `..` segments, so the `is_relative_to` check works for `../../../etc/passwd`. However, there are edge cases:

1. If `comp.root_dir` is a symlink, `resolve()` follows it, which could make the check pass for paths outside the logical workspace.
1. On Windows, UNC paths (`\\server\share`) or drive-letter switches (`D:\secret`) passed as `path` will be joined incorrectly by `/` (Python's `PurePosixPath.__truediv__` handles absolute segments by replacing the base), but `pathlib.Path` on Windows will keep the absolute path, causing `is_relative_to` to correctly reject it.

The symlink scenario is the real risk: if `root_dir` contains a symlink pointing outside the workspace, `resolve()` follows it, and a path like `symlink/../../../etc/passwd` resolves to something outside. **Mitigation:** Also check `full_path.is_relative_to(comp.root_dir)` (without resolve) to catch symlink escapes, or use `os.path.realpath` on both and compare.

**File:** `mcp_server.py:202-203`

### R21-M6: MCP tools mix sync and async without executor (Major)

Tools `search_vault`, `search_codebase`, `search_all`, `reindex_vault`, `reindex_codebase` are declared `async` (lines 110, 131, 169, 214, 243) but call synchronous blocking code: GPU inference (`model.encode_query`), Qdrant I/O (`store.hybrid_search`), and model loading. These block the asyncio event loop, preventing concurrent MCP request handling. The MCP server will appear to hang during long operations (model loading can take 10+ seconds).

**Fix:** Run blocking calls via `asyncio.to_thread()` or `loop.run_in_executor()`.

**File:** `mcp_server.py:110-127, 131-165, 169-180, 214-239, 243-269`

### R21-M7: `get_comp()` is not thread-safe and has no error recovery (Major)

Line 43-62: `get_comp()` uses a module-level `_comp` global with no locking. If two async MCP requests arrive simultaneously before initialization completes, both will try to create RAG components, loading GPU models twice and potentially causing CUDA OOM. Additionally, if initialization fails (e.g., no GPU), `_comp` stays `None` and every subsequent request retries the expensive failing initialization.

**Fix:** Use `asyncio.Lock` or `threading.Lock` around initialization, and cache failures to fail fast.

**File:** `mcp_server.py:40-62`

### R21-m10: `get_index_status` and `get_code_file` are sync but other tools are async (Minor)

Lines 184 and 195: `get_index_status` and `get_code_file` are synchronous functions registered as MCP tools, while all other tools are async. FastMCP handles this, but mixing sync/async tools is inconsistent.

**File:** `mcp_server.py:184, 195`

### R21-m11: `reindex_vault` `clean=True` calls `full_index()` but does not clear the collection first (Minor)

Line 229: `comp.vault_indexer.full_index()` is called when `clean=True`. Whether this actually drops and recreates the collection depends on `VaultIndexer.full_index()` implementation. The MCP tool name and docstring imply a clean re-index, but if `full_index()` is additive, stale documents will persist. Should verify `VaultIndexer.full_index()` behavior matches the promise.

**File:** `mcp_server.py:228-229`

### R21-m12: No input validation on `top_k` parameter (Minor)

All search tools accept `top_k: int = 5` with no bounds checking. A caller can pass `top_k=0` (returns empty), `top_k=-1` (undefined Qdrant behavior), or `top_k=10000` (expensive query). Should clamp to a reasonable range like `1..100`.

**File:** `mcp_server.py:111, 133, 170`

### R21-m13: `SearchResultItem` duplicates `SearchResult` fields (Minor)

`SearchResultItem` (line 66-85) is a Pydantic mirror of the `SearchResult` dataclass from `search.py`. If fields are added to `SearchResult`, `SearchResultItem` must be manually updated. Consider generating one from the other or using a shared schema.

**File:** `mcp_server.py:66-85`

### R21-m14: `IndexResponse.files` field defaults to 0, potentially misleading for vault reindex (Minor)

Line 105: `files: int = Field(default=0, ...)`. For vault reindex (line 233-239), the `files` field is not set, so it defaults to 0. This is technically correct (vault indexer result may not have a `files` attribute), but the response will show `files: 0` which could confuse users into thinking no files were processed.

**File:** `mcp_server.py:105, 233-239`
