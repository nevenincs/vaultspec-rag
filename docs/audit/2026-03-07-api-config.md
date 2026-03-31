# Round 24 Audit -- api.py, config.py

## api.py

### R24-M1: `get_engine` leaks old Qdrant client when root_dir changes (Major)

Line 53-54: When `_engine.root_dir != root_dir`, a new `_Engine` is created and assigned to `_engine`, but the old engine's `store.close()` is never called. The old `QdrantClient` retains file handles and lock files on the `.qdrant/` directory. On Windows this causes `PermissionError` if the new engine targets the same directory. Even for different directories, file descriptors are leaked until GC finalizes the object.

**Fix:** Call `_engine.store.close()` before replacing:

```python
if _engine is not None and _engine.root_dir != root_dir:
    _engine.store.close()
    _engine = _Engine(root_dir)
```

**File:** `api.py:50-55`

### R24-M2: `get_related` never returns `None` despite docstring (Major)

Lines 150-177: The docstring says "or None if the document is not found", but:

- Graph build failure (line 167): returns `{"doc_id": ..., "outgoing": [], "incoming": []}`
- Node not found (line 171): returns `{"doc_id": ..., "outgoing": [], "incoming": []}`

The function **never** returns `None`. Any caller checking `if result is None` will never detect these failure cases. Either the docstring is wrong or the implementation is -- they disagree.

**File:** `api.py:150-177`

### R24-M3: Module-level imports eagerly trigger GPU model loading on import (Major)

Lines 16-19: `api.py` imports `EmbeddingModel`, `VaultIndexer`, `CodebaseIndexer`, `VaultSearcher`, `VaultStore` at module level. These are further re-exported from `__init__.py` (lines 9-26). This means `import vaultspec_rag` or `from vaultspec_rag import list_documents` triggers:

- `from .embeddings import EmbeddingModel` which imports `sentence_transformers` at class definition time (no, it's deferred -- only `_check_rag_deps` calls it)
- However, `from .store import VaultStore` imports `qdrant_client` at `_check_rag_deps` time

Actually, the imports are deferred inside `__init__` and `_check_rag_deps`. The module-level imports in api.py import the *classes* but don't instantiate them. GPU loading only happens when `_Engine.__init__` runs. So this is less severe than initially assessed.

**Severity downgrade:** Minor. The real cost is that `import vaultspec_rag` loads the `.store`, `.embeddings`, `.indexer`, `.search` modules, which in turn import `vaultspec.vaultcore`, `vaultspec.config`, etc. This is a startup cost but not a GPU load.

### R24-m1: `get_engine` path comparison not normalized (Minor)

Line 53: `_engine.root_dir != root_dir` compares `pathlib.Path` objects directly. `Path("./project")` and `Path("project")` compare as unequal even though they resolve to the same directory. Similarly, `Path("C:\\project")` vs `Path("c:\\project")` on Windows (case sensitivity). This can cause unnecessary engine recreation and the resource leak from R24-M1.

**Fix:** Compare using `.resolve()`: `_engine.root_dir.resolve() != root_dir.resolve()`

**File:** `api.py:53`

### R24-m2: `get_engine` is not thread-safe (Minor)

Lines 50-55: The global `_engine` is read and written without any locking. If two threads call `get_engine` concurrently with the same `root_dir`:

1. Thread A sees `_engine is None`, starts creating `_Engine`
2. Thread B sees `_engine is None`, also starts creating `_Engine`
3. Both load GPU models, doubling VRAM usage
4. One assignment overwrites the other, leaking one engine

For the CLI this is single-threaded and fine. For MCP server usage (which has its own `get_comp()` singleton), this is also not hit. But the API facade is public and documented, so concurrent use is plausible.

**File:** `api.py:50-55`

### R24-m3: `search_codebase` facade does not expose filter kwargs (Minor)

Lines 117-131: `VaultSearcher.search_codebase` accepts `language`, `node_type`, `function_name`, `class_name` keyword arguments, but the API facade only passes `query` and `top_k`. Users of the public API cannot filter codebase searches without dropping down to `get_engine().searcher.search_codebase()`.

**File:** `api.py:117-131`

### R24-m4: `search_all` not exposed in API facade (Minor)

`VaultSearcher` has `search_all()` and `search()` methods that search both vault and codebase. The API facade only exposes `search_vault` and `search_codebase` separately. There is no `search_all` function in the facade, so users wanting combined results must call both and merge manually.

**File:** `api.py` (missing function)

### R24-m5: `__all__` exports `get_engine` and `reset_engine` -- internal functions in public API (Minor)

Lines 23-32: `get_engine` returns an `_Engine` instance (underscore-prefixed, private class). `reset_engine` is documented "for testing". Both are exported in `__all__`, making private internals part of the public API surface. However, `get_engine` is not re-exported from `__init__.py`, so it's only visible via `from vaultspec_rag.api import get_engine`.

**File:** `api.py:23-32`

### R24-m6: `get_related` builds a fresh VaultGraph on every call (Minor)

Line 164: `graph = VaultGraph(root_dir)` constructs a new graph every time `get_related` is called. Unlike `VaultSearcher._get_graph()` which caches the graph with a TTL, the API facade rebuilds it from scratch on each invocation. For repeated calls (e.g., displaying related docs for a list of search results), this is O(n) graph builds.

**File:** `api.py:164`

## config.py

### R24-M4: `__getattr__` returns `Any` -- no type safety for config values (Major)

Line 21: `def __getattr__(self, name: str) -> Any` returns untyped values. Callers access config attributes like `cfg.embedding_batch_size` but get no type checking. If the base config returns a string `"64"` instead of int `64` for `embedding_batch_size`, the error surfaces much later (e.g., during batch processing) with a confusing traceback.

The `rag_defaults` dict (lines 23-36) defines correct types, but if the base config overrides a value with the wrong type, it passes through unchecked.

**File:** `config.py:21`

### R24-M5: `__getattr__` re-creates `rag_defaults` dict on every attribute access (Major)

Lines 22-36: The `rag_defaults` dict literal is constructed inside `__getattr__`, which is called for every attribute access on the wrapper. In a tight loop (e.g., embedding batches checking `cfg.embedding_batch_size` and `cfg.max_embed_chars`), this allocates a new dict with 12 entries on each access. Should be a class attribute or `__init__` assignment.

**File:** `config.py:22-36`

### R24-m7: `get_config` with overrides does not update the cached singleton (Minor)

Lines 64-66: When `overrides` is not None, a fresh wrapper is created and returned *without* updating `_cached_config`. This means:

1. Call `get_config({"embedding_batch_size": 128})` -- returns wrapper with batch_size=128
2. Call `get_config()` -- returns cached singleton with default batch_size=64

This is documented behavior ("When called without overrides, returns a cached singleton") but can cause confusion: the overrides from step 1 are silently forgotten by step 2. Any code that calls `get_config()` (without overrides) after an override call gets stale defaults.

**File:** `config.py:64-66`

### R24-m8: `VaultSpecConfigWrapper` does not support `hasattr` correctly for non-RAG attributes (Minor)

Line 21-44: Python's `hasattr(obj, name)` calls `getattr` and checks for `AttributeError`. For RAG attributes in `rag_defaults`, `hasattr` always returns `True` (default is returned). For non-RAG attributes, `hasattr` depends on `getattr(self._base, name)` on line 44. If the base config raises `AttributeError`, `hasattr` correctly returns `False`.

However, if the base config raises a *different* exception (e.g., `ValueError` from validation), `hasattr` in Python < 3.12 propagates the exception instead of returning `False`. In Python 3.12+ this was changed to only catch `AttributeError`. Since the project targets Python 3.13, this is fine. No bug here.

**Severity:** Not a bug. Removed.

### R24-m9: `reset_config` does not clear the base config cache (Minor)

Line 73-76: `reset_config` sets `_cached_config = None` but does not call `reset` on the base `get_base_config` cache (if one exists in `vaultspec.config`). If the base config also caches, calling `reset_config` then `get_config` returns a new wrapper around the *same* stale base config. This may not be an issue if the base config has no cache, but it's a potential gotcha.

**File:** `config.py:73-76`

### R24-m10: No validation that `qdrant_dir` does not escape workspace (Minor)

Line 24: `"qdrant_dir": ".qdrant"`. If the base config overrides this to something like `"../../shared_qdrant"`, `VaultStore.__init__` will create the directory outside the workspace root. There is no validation that `qdrant_dir` is a relative path that stays within `root_dir`.

**File:** `config.py:24`

### R24-m11: `from_environment` classmethod is never called (Minor)

Lines 46-52: `VaultSpecConfigWrapper.from_environment()` is defined but not used anywhere in the codebase. All callers use `get_config()` instead. This is dead code.

**File:** `config.py:46-52`
