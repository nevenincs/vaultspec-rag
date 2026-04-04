---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
---

# Round 22 Audit -- indexer.py, store.py, api.py

## indexer.py

### R22-M1: `_scan_codebase` reads every `.gitignore` via `rglob`, including inside ignored directories (Major)

Line 879: `self.root_dir.rglob(".gitignore")` walks the entire directory tree including `.venv/`, `node_modules/`, `.git/`, etc. before any ignore rules are applied. On large projects this can be extremely slow (e.g., scanning all of `node_modules/` to find nested `.gitignore` files). The hardcoded exclusion patterns on lines 872-878 only apply to the pathspec filter, not to the `rglob` traversal itself.

**File:** `indexer.py:879`

### R22-M2: `_scan_codebase` reads entire files to check for binary content (Major)

Line 272-278: `_is_binary` reads up to 8192 bytes via `path.read_bytes()[:sample_size]`. This is called for every file that passes the extension and gitignore filters (line 914). However, `read_bytes()` without a size hint reads the entire file into memory first, then slices. For a 9.9 MB file (just under `_MAX_FILE_SIZE`), this allocates ~10 MB just to check for null bytes. Should use `open(path, 'rb').read(sample_size)` instead.

**File:** `indexer.py:275`

### R22-M3: `TextSplitter._recursive_split` overlap logic produces chunks larger than `chunk_size` (Major)

Line 130-134: When a chunk overflows, the overlap logic does:

```python
overlap_start = max(0, len(current_chunk) - self.chunk_overlap)
current_chunk = current_chunk[overlap_start:] + separator + s
```

If the overlap portion (`current_chunk[overlap_start:]`) plus `separator` plus `s` exceeds `chunk_size`, the resulting `current_chunk` will be oversized. This is caught by the post-check on line 142 which recurses, but the recursion uses the *next* separator which may not split effectively, potentially producing chunks well over the budget.

**File:** `indexer.py:130-134`

### R22-m1: `VaultIndexer.full_index` delete-then-upsert is not atomic (Minor)

Lines 681-692: `full_index()` deletes all existing documents, then upserts new ones. If the process crashes between delete and upsert, the index is empty. The upsert alone (with Qdrant's point ID deduplication via `_stable_id`) would overwrite existing points, so the delete step is only needed to remove docs that no longer exist. A safer approach: upsert first, then delete IDs not in the new set.

**File:** `indexer.py:681-692`

### R22-m2: `CodebaseIndexer.full_index` reads every file twice -- once for hashing, once for chunking (Minor)

Lines 1027-1030 hash every file via `p.read_bytes()`, then lines 1036-1039 read each file again in `_chunk_file` via `path.read_text()`. For large codebases this doubles I/O. The content could be read once and passed to both hash and chunk.

**File:** `indexer.py:1027-1030, 1036-1039`

### R22-m3: `CodebaseIndexer.incremental_index` also reads files twice for hash + chunk (Minor)

Same pattern as full_index: lines 1101-1105 hash files, then lines 1128-1132 re-read them for chunking. Same fix: read once, hash the bytes, decode for chunking.

**File:** `indexer.py:1101-1105, 1128-1132`

### R22-m4: `ASTChunker._merge_small` merges chunks across function/class boundaries (Minor)

Lines 492-512: When two adjacent chunks are both under half the budget, they are merged regardless of whether they belong to different functions or classes. The merge keeps `prev[4] or chunk[4]` for `function_name` (first non-None wins), which means the second chunk's function_name is silently discarded. This could attribute code from function B to function A in search results.

**File:** `indexer.py:510-511`

### R22-m5: `_extract_feature` returns the first non-DocType tag, which may not be the feature tag (Minor)

Line 543-546: If a document has tags `["#plan", "#rag", "#search"]`, and `#plan` is a DocType, the function returns `"rag"`. But if the document is about `#search` and `#rag` is a secondary tag, the wrong feature is extracted. The function has no way to distinguish feature tags from other non-DocType tags.

**File:** `indexer.py:543-546`

### R22-m6: `ASTChunker` creates a new parser instance on every `chunk()` call (Minor)

Line 312: `parser = get_parser(grammar)` is called per file. If `get_parser` doesn't cache internally, this creates N parser instances for N files. tree-sitter-language-pack likely caches, but this is worth verifying.

**File:** `indexer.py:312`

## store.py

### R22-M4: `_build_filter` uses `MatchText` for date filter -- full-text search instead of prefix match (Major)

Line 657-662: The `date` filter uses `models.MatchText(text=value)`. Qdrant's `MatchText` performs full-text search (tokenized), not substring/prefix matching. For a date like `"2026-02"`, this will tokenize on `-` and match any document containing `"2026"` OR `"02"` depending on the analyzer. The intended behavior is likely prefix matching (all docs from February 2026). Should use `MatchValue` for exact dates or a range filter for date prefixes.

**File:** `store.py:657-662`

### R22-M5: `hybrid_search` calls `self.count()` on every query, adding a round-trip (Major)

Line 517: `if self.count() == 0: return []`. This executes a Qdrant count query on every search call just to check for emptiness. For a hot search path, this adds unnecessary latency. The Qdrant query itself will return empty results if the collection is empty, so this guard is redundant.

**File:** `store.py:517`
**Also:** `store.py:581` (same pattern in `hybrid_search_codebase`)

### R22-m7: `_stable_id` hash collision risk with 63-bit truncation (Minor)

Line 713-714: SHA-256 is truncated to 63 bits (`& 0x7FFFFFFFFFFFFFFF`). With the birthday paradox, collision probability exceeds 1% at ~136 million documents. For typical vault/codebase sizes (thousands of documents) this is fine, but worth documenting the limit. A collision would silently overwrite a different document.

**File:** `store.py:713-714`

### R22-m8: `ensure_table` and `ensure_code_table` call `collection_exists` on every operation (Minor)

Lines 187 and 203: Every `upsert_documents`, `delete_documents`, `count`, etc. call triggers `ensure_table` which does a `collection_exists` RPC to Qdrant. After the first call, the collection is guaranteed to exist for the lifetime of the VaultStore instance. A simple boolean flag (`_vault_table_created`) would eliminate repeated checks.

**File:** `store.py:183-197, 199-213`

### R22-m9: `_build_filter` and `_build_code_filter` silently ignore unknown filter keys (Minor)

Lines 656-677 and 692-699: If a filter dict contains a key not in the whitelist (e.g., `{"title": "foo"}`), it is silently dropped. No warning is logged, so users may think their filter is applied when it is not.

**File:** `store.py:656-677, 692-699`

### R22-m10: `upsert_documents` does not batch large upserts (Minor)

Lines 256-259: All points are upserted in a single `self._client.upsert()` call regardless of count. For very large vaults (thousands of documents with full content payloads), this could exceed Qdrant's gRPC message size limits or cause memory pressure. Batching in groups of 100-500 would be safer.

**File:** `store.py:256-259`
**Also:** `store.py:303-306` (same for `upsert_code_chunks`)

## api.py

### R22-M6: `get_engine` silently discards old engine when `root_dir` changes without closing it (Major)

Line 53: `if _engine is None or _engine.root_dir != root_dir:` creates a new engine, but when `_engine.root_dir != root_dir`, the old engine's `store.close()` is never called. The old Qdrant client is leaked (file handles, lock files). Only `reset_engine()` properly closes the store.

**File:** `api.py:50-55`

### R22-m11: `get_related` returns a dict on error instead of `None` (Minor)

Line 167: The docstring says "or None if the document is not found", but when the graph build fails (line 165-167), it returns `{"doc_id": doc_id, "outgoing": [], "incoming": []}` instead of `None`. Same on line 171 when the node is not found. Callers checking `if result is None` will never detect these failure cases.

**File:** `api.py:150-177`

### R22-m12: `get_engine` uses `!=` path comparison which is not normalized (Minor)

Line 53: `_engine.root_dir != root_dir` compares `pathlib.Path` objects. If one path is `Path("./foo")` and another is `Path("foo")`, they compare as unequal even though they refer to the same directory. Should use `.resolve()` for comparison.

**File:** `api.py:53`

### R22-m13: Module-level imports eagerly load GPU code (Minor)

Lines 16-19: `api.py` imports `EmbeddingModel`, `VaultIndexer`, `CodebaseIndexer`, `VaultSearcher`, `VaultStore` at module level. Importing `EmbeddingModel` triggers `from sentence_transformers import ...` which loads torch. Any code that does `from vaultspec_rag.api import list_documents` will pay the torch import cost even if they only need metadata queries. The imports should be deferred to `_Engine.__init__`.

**File:** `api.py:16-19`

### R22-m14: `search_codebase` in api.py does not expose filter kwargs (Minor)

Line 117-131: The `search_codebase` facade only accepts `query` and `top_k`, but `VaultSearcher.search_codebase` supports `language`, `node_type`, `function_name`, `class_name` keyword arguments. API users cannot filter codebase searches without dropping down to the engine directly.

**File:** `api.py:117-131`
