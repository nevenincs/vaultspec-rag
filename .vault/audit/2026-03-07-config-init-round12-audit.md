---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
related: []
---

# Round 12 Audit -- config.py and __init__.py

__Auditor:__ docs-researcher-2-2
__Files:__ `src/vaultspec_rag/config.py` (78 lines), `src/vaultspec_rag/__init__.py` (52 lines), cross-ref `src/vaultspec_rag/api.py` (264 lines)
__Date:__ 2026-03-07

______________________________________________________________________

## config.py Audit

### Check 1: RAG Defaults Coverage

`_RAG_DEFAULTS` (lines 18-31) provides defaults for 12 keys:

| Key                    | Default                       | Used by                                      |
| ---------------------- | ----------------------------- | -------------------------------------------- |
| `qdrant_dir`           | `".qdrant"`                   | store.py:138, indexer.py:632, indexer.py:874 |
| `index_metadata_file`  | `"index_meta.json"`           | indexer.py:632 (VaultIndexer only)           |
| `graph_ttl_seconds`    | `300.0`                       | search.py:184                                |
| `embedding_batch_size` | `64`                          | embeddings.py:133                            |
| `max_embed_chars`      | `8000`                        | embeddings.py:140                            |
| `embedding_model`      | `"Qwen/Qwen3-Embedding-0.6B"` | embeddings.py:161                            |
| `embedding_dimension`  | `1024`                        | embeddings.py:194                            |
| `sparse_model`         | `"naver/splade-v3"`           | embeddings.py:163                            |
| `rag_enabled`          | `True`                        | (not found in source -- dead key)            |
| `reranker_enabled`     | `True`                        | search.py:191                                |
| `reranker_model`       | `"BAAI/bge-reranker-v2-m3"`   | search.py:192                                |
| `reranker_top_k`       | `5`                           | (not found in source -- dead key)            |

__Verdict: PASS__ on coverage. All active RAG config keys have defaults.

#### R12-m1: `rag_enabled` config key is dead -- never read by any module (Minor)

Defined at config.py:27 but never referenced in any source file. No code checks `cfg.rag_enabled` to gate RAG functionality.

__File:__ `config.py:27`

#### R12-m2: `reranker_top_k` config key is dead -- never read by any module (Minor)

Defined at config.py:30 but never referenced. The reranker in `search.py:_rerank()` receives `top_k` from the caller (search method parameter), not from config. Previously flagged in Round 7 as `_reranker_top_k` dead field on VaultSearcher -- the config key was likely the source of that dead field, both now orphaned.

__File:__ `config.py:30`

______________________________________________________________________

### Check 2: `get_config()` Caching

```python
_cached_config: VaultSpecConfigWrapper | None = None

def get_config(overrides: dict[str, Any] | None = None) -> VaultSpecConfigWrapper:
    global _cached_config
    if overrides is not None:
        base = get_base_config(overrides)
        _cached_config = VaultSpecConfigWrapper(base)
        return _cached_config
    if _cached_config is None:
        base = get_base_config()
        _cached_config = VaultSpecConfigWrapper(base)
    return _cached_config
```

__Verdict: PASS.__ Module-level `_cached_config` singleton, shared across the process. First call creates and caches. Subsequent calls return cached instance. Calling with `overrides` replaces the cached instance.

`reset_config()` (line 74-77) clears the cache for testing.

#### R12-m3: `get_config()` is not thread-safe (Minor)

No lock protects `_cached_config`. If two threads call `get_config()` simultaneously during first init, both may create a `VaultSpecConfigWrapper`, with one overwriting the other. Since both would have the same config values, this is a benign race -- the only cost is one redundant `VaultSpecConfigWrapper` creation. Not a real bug.

__File:__ `config.py:57-71`

______________________________________________________________________

### Check 3: Hardcoded Config Values in Other Modules

| Module              | Value                      | Config key             | Assessment                                                                |
| ------------------- | -------------------------- | ---------------------- | ------------------------------------------------------------------------- |
| `embeddings.py:124` | `DEFAULT_DIMENSION = 1024` | `embedding_dimension`  | __OK__ -- class-level fallback, overridden by config at line 194          |
| `embeddings.py:125` | `DEFAULT_BATCH_SIZE = 64`  | `embedding_batch_size` | __OK__ -- class-level fallback, `_default_batch_size()` reads config      |
| `embeddings.py:126` | `MAX_EMBED_CHARS = 8000`   | `max_embed_chars`      | __OK__ -- class-level fallback, `_default_max_embed_chars()` reads config |
| `store.py:25`       | `EMBEDDING_DIM = 1024`     | `embedding_dimension`  | __OK__ -- module-level fallback, overridden by `__init__` param           |
| `search.py:233`     | `batch_size=32`            | (none)                 | __Hardcoded__ -- reranker predict batch size not in config                |
| `embeddings.py:275` | `batch_size: int = 32`     | (none)                 | __Hardcoded__ -- sparse encoder batch size not in config                  |
| `indexer.py:874`    | `"code_index_meta.json"`   | (none)                 | __Hardcoded__ -- see R12-M1 below                                         |

#### R12-M1: CodebaseIndexer hardcodes `"code_index_meta.json"` instead of using config (MEDIUM)

`VaultIndexer.__init__` (indexer.py:632) uses `cfg.index_metadata_file` for its metadata path:

```python
self._meta_path = root_dir / cfg.qdrant_dir / cfg.index_metadata_file
```

But `CodebaseIndexer.__init__` (indexer.py:874) hardcodes the filename:

```python
self._meta_path = root_dir / cfg.qdrant_dir / "code_index_meta.json"
```

This is actually intentional -- vault and codebase need __different__ metadata files (they track different sets of documents). Using the same `cfg.index_metadata_file` for both would overwrite vault metadata with codebase metadata.

However, the codebase metadata filename is not configurable at all. If `cfg.index_metadata_file` is changed from its default `"index_meta.json"`, the vault file moves but the codebase file stays at `"code_index_meta.json"`. This inconsistency could confuse administrators.

__Severity: downgraded to MINOR__ -- intentionally different files, but the codebase filename should probably have its own config key (e.g., `code_index_metadata_file`).

__File:__ `indexer.py:874`

#### R12-m4: Sparse encoder and reranker batch sizes are hardcoded (Minor)

`encode_documents_sparse` (embeddings.py:275) defaults to `batch_size=32` instead of reading `self._default_batch_size()` like `encode_documents` does. The reranker `predict()` at search.py:233 also hardcodes `batch_size=32`. Neither has a config key. These may justify different defaults from the dense encoder (different memory profiles), but the inconsistency is undocumented.

__File:__ `embeddings.py:275`, `search.py:233`

______________________________________________________________________

### Check 4: `reranker_enabled` Config

```python
"reranker_enabled": True,   # config.py:28
```

Read by `VaultSearcher.__init__` (search.py:191):

```python
self._reranker_enabled: bool = cfg.reranker_enabled
```

Used in `_rerank()` (search.py:229):

```python
if not self._reranker_enabled or len(results) <= 1:
    return results[:top_k]
```

__Verdict: PASS.__ `reranker_enabled` is a config key, defaults to `True`, and correctly gates the CrossEncoder reranker.

______________________________________________________________________

### Check 5: Circular Import Risks

All 10 `from .config import get_config` calls across the codebase are __deferred__ (inside function/method bodies, not at module level):

- `embeddings.py`: lines 131, 138, 158 (inside static methods and `__init__`)
- `indexer.py`: lines 577, 625, 733, 824, 871 (inside functions and methods)
- `search.py`: line 180 (inside `__init__`)
- `store.py`: line 133 (inside `__init__`)

`config.py` itself imports only from `vaultspec.config` (the base package), not from any sibling modules. No circular import risk.

__Verdict: PASS.__ Clean import graph with deferred imports.

______________________________________________________________________

## __init__.py Audit

### Check 1: Exports

`__init__.py` exports 19 names from 4 modules:

| Module        | Exports                                                                                                     |
| ------------- | ----------------------------------------------------------------------------------------------------------- |
| `.api`        | `get_related`, `index`, `index_codebase`, `list_documents`, `search_all`, `search_codebase`, `search_vault` |
| `.embeddings` | `EmbeddingModel`, `SparseResult`                                                                            |
| `.indexer`    | `CodebaseIndexer`, `IndexResult`, `VaultIndexer`, `prepare_document`                                        |
| `.search`     | `ParsedQuery`, `SearchResult`, `VaultSearcher`, `parse_query`, `rerank_with_graph`                          |
| `.store`      | `CodeChunk`, `VaultDocument`, `VaultStore`                                                                  |

______________________________________________________________________

### Check 2: Public API Type Coverage

Expected public types and their export status:

| Type                | Exported? |
| ------------------- | --------- |
| `VaultStore`        | Yes       |
| `VaultIndexer`      | Yes       |
| `CodebaseIndexer`   | Yes       |
| `EmbeddingModel`    | Yes       |
| `VaultSearcher`     | Yes       |
| `SparseResult`      | Yes       |
| `SearchResult`      | Yes       |
| `ParsedQuery`       | Yes       |
| `CodeChunk`         | Yes       |
| `VaultDocument`     | Yes       |
| `IndexResult`       | Yes       |
| `prepare_document`  | Yes       |
| `parse_query`       | Yes       |
| `rerank_with_graph` | Yes       |

__Verdict: PASS.__ All public types are exported.

______________________________________________________________________

### Check 3: Missing Exports for `api.py` Facade Users

The `api.py` facade exports these functions: `get_engine`, `reset_engine`, `get_related`, `index`, `index_codebase`, `list_documents`, `search_all`, `search_codebase`, `search_vault`.

The `__init__.py` re-exports 7 of 9 from `api.py`:

- Exported: `get_related`, `index`, `index_codebase`, `list_documents`, `search_all`, `search_codebase`, `search_vault`
- __Not exported:__ `get_engine`, `reset_engine`

#### R12-m5: `get_engine` and `reset_engine` not exported from `__init__.py` (Minor)

`api.py` exports `get_engine` and `reset_engine` in its own `__all__`, but `__init__.py` does not re-export them. Users must import via `from vaultspec_rag.api import get_engine`. This is likely intentional -- `get_engine` returns a private `_Engine` type, and `reset_engine` is a test utility. But it's worth documenting.

__File:__ `__init__.py:9-17`, `api.py:26-36`

______________________________________________________________________

### Check 4: Consistency with `api.py` Internal Usage

`api.py` internally imports:

- `EmbeddingModel` from `.embeddings` (line 19)
- `CodebaseIndexer`, `IndexResult`, `VaultIndexer` from `.indexer` (line 20)
- `SearchResult`, `VaultSearcher` from `.search` (line 21)
- `VaultStore` from `.store` (line 22)
- `VaultGraph` from `vaultspec.graph` (TYPE_CHECKING, line 17)

All types used by `api.py` are available in `__init__.py` exports.

The return types of `api.py` functions:

- `index()` -> `IndexResult` -- exported
- `index_codebase()` -> `IndexResult` -- exported
- `search_vault()` -> `list[SearchResult]` -- exported
- `search_codebase()` -> `list[SearchResult]` -- exported
- `search_all()` -> `list[SearchResult]` -- exported
- `list_documents()` -> `list[dict]` -- no custom type needed
- `get_related()` -> `dict | None` -- no custom type needed

__Verdict: PASS.__ All return types are available to consumers of the public API.

______________________________________________________________________

## Additional Observations

### `__init__.py` eager imports trigger GPU model loading

`__init__.py` imports `EmbeddingModel` from `.embeddings` at module level (line 18). Since `embeddings.py` only defines the class (does not instantiate it), this does NOT trigger GPU model loading. The `_check_rag_deps()` call is inside `EmbeddingModel.__init__()`, not at import time. Safe.

However, `__init__.py` also imports from `.api` (line 9-17), which imports `EmbeddingModel` from `.embeddings` at module level (api.py:19). Again, class import only -- no instantiation. Safe.

### `VaultSpecConfigWrapper.__getattr__` returns bare `Any`

Line 36: `def __getattr__(self, name: str) -> Any:` -- the return type is `Any`, which means all config access is untyped. This is a trade-off of the wrapper pattern: type checkers cannot verify config attribute access. Not a bug, but a typing limitation.

______________________________________________________________________

## Summary

| ID     | Severity | Finding                                                                          |
| ------ | -------- | -------------------------------------------------------------------------------- |
| R12-m1 | MINOR    | `rag_enabled` config key is dead -- never read                                   |
| R12-m2 | MINOR    | `reranker_top_k` config key is dead -- never read                                |
| R12-m3 | MINOR    | `get_config()` has benign race on first init (no lock)                           |
| R12-m4 | MINOR    | Sparse encoder and reranker batch sizes hardcoded (not configurable)             |
| R12-m5 | MINOR    | `get_engine` and `reset_engine` not re-exported from `__init__.py` (intentional) |

Note: The `CodebaseIndexer` hardcoded `"code_index_meta.json"` (indexer.py:874) was initially flagged as MEDIUM but downgraded to MINOR on analysis -- vault and codebase intentionally use separate metadata files.

__0 HIGH/MEDIUM findings. 5 MINOR findings.__
