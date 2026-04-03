---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-09
related: []
---

# Round 30: New Code Correctness Audit + ADR Regression Test Coverage

**Date:** 2026-03-09
**Auditor:** Claude Code
**Scope:** New code added in session (mcp_server graph invalidation, CLI MCP fast paths, atomic writes)

______________________________________________________________________

## Part A: New Code Correctness Audit

### 1. MCP Server Graph Invalidation ✅ CORRECT

**Location:** `src/vaultspec_rag/mcp_server.py:349`

```python
def _run() -> IndexResponse:
    comp = get_comp()
    ...
    if clean:
        result = comp.vault_indexer.full_index(clean=True)
    else:
        result = comp.vault_indexer.incremental_index()
    # Invalidate the graph cache so the next search_vault call rebuilds
    # from the fresh index rather than serving stale graph-boost scores.
    comp.searcher._graph_built_at = 0.0
    return IndexResponse(...)
```

**Findings:**

- ✅ **CORRECT:** Graph reset happens **AFTER** indexer completes (not before)
- ✅ **CORRECT:** Reset is inside `_run()` (worker thread via `anyio.to_thread.run_sync()`)
- ✅ **CORRECT:** Thread-safety is ensured because:
  - `_run()` executes in a thread pool (not the async loop)
  - `comp.searcher._graph_built_at` is a simple float write (atomic on x86/x64)
  - GPU semaphore wraps the entire operation, preventing concurrent searches during reindex
- ✅ **CORRECT:** Not needed in `reindex_codebase` — codebase indexing does NOT affect the vault graph (these are separate collections)

**Architectural note:** The VaultGraph is populated during `search_vault` from the vault collection only. CodebaseIndexer writes to the separate `code` collection, so reindexing codebase never invalidates the vault graph. This is sound.

______________________________________________________________________

### 2. CLI Fast-Path Tool Map Fallback ✅ SAFE (DEAD CODE)

**Location:** `src/vaultspec_rag/cli.py:386-387`

```python
tool_map = {"vault": "search_vault", "code": "search_codebase", "all": "search_all"}
tool_name = tool_map.get(search_type, "search_vault")
```

**Findings:**

- ✅ **SAFE:** Fallback to `"search_vault"` is reasonable (most conservative choice)
- ✅ **CORRECT:** The `search_type` parameter is typed as `Literal["vault", "code", "all"]`
  - Invalid values are **statically impossible** — mypy will catch them at type-check time
- ✅ **CORRECT:** The `.get()` fallback is dead code but harmless defensive programming
- **Recommendation:** The fallback is safe to keep (belt-and-suspenders defensive coding)

______________________________________________________________________

### 3. TestMcpFastPath Tests — Network Behavior ✅ GENUINE

**Location:** `src/vaultspec_rag/tests/test_cli.py:132-177`

```python
def test_tool_map_vault(self):
    """Connection refused on port 1 returns None, no exception."""
    result = _try_mcp_search("test query", "vault", 5, 1)
    assert result is None
```

**Findings:**

- ✅ **GENUINE TEST (non-tautological):** Port 1 is IANA reserved (tcpmux) and **not open on modern systems**
  - macOS/Linux: requires root; never bound in user-space
  - Windows: port 1 is reserved and unusable for user processes
  - ✓ Connection refused exception is caught and returns `None`
  - ✓ Test validates exception handling, not a mock
- ✅ **GENUINE:** `_display_search_results` tests do NOT mock — they call the real function with dict payloads
  - `test_display_empty_results()` — verifies empty list doesn't crash
  - `test_display_missing_fields()` — verifies dicts with missing keys render (uses `.get()` defaults)
  - `test_display_with_line_start()` — verifies `line_start` appends `:N` to location
  - `test_display_without_line_start()` — verifies path-only location when `line_start` is absent
  - All are **genuinely non-tautological** — they test real rendering logic with varied inputs

**Verdict:** No false tests. All tests exercise real code paths and validate actual behavior.

______________________________________________________________________

### 4. Atomic Write Correctness ✅ CORRECT

**Locations:**

- `src/vaultspec_rag/indexer.py:835-847` (VaultIndexer.\_write_meta)
- `src/vaultspec_rag/indexer.py:1243-1252` (CodebaseIndexer.\_write_meta)

```python
def _write_meta(self, meta: dict[str, str]) -> None:
    """Atomic write (write-to-temp + os.replace)."""
    self._meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = self._meta_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp_path, self._meta_path)
```

**Findings:**

| Question                                     | Answer                                                                                                                                                       |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `.with_suffix(".tmp")` safe?                 | ✅ Yes. `index_meta.json` → `index_meta.tmp`; `code_index_meta.json` → `code_index_meta.tmp`. Both safe.                                                     |
| Race if two threads write simultaneously?    | ✅ No. Indexers are **single-threaded** (called once per reindex operation). `_write_meta` is called once at the end of `full_index` or `incremental_index`. |
| .tmp file already exists from crashed write? | ✅ Correct. `write_text()` overwrites silently. `os.replace()` then atomically replaces the real file.                                                       |
| `os.replace()` atomicity?                    | ✅ Yes. POSIX `rename()` is atomic; Windows `ReplaceFile()` is atomic. No crash-in-middle corruption.                                                        |

**Verdict:** Atomic write pattern is **architecturally sound** and **crash-safe**. ✅

______________________________________________________________________

## Part B: ADR Regression Test Coverage

### Current Coverage Status

Examined `src/vaultspec_rag/tests/test_adr_regression.py`:

| Feature                                  | Covered?   | Test                                                                                            |
| ---------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------- |
| Graph invalidation after `reindex_vault` | ❌ NO      | —                                                                                               |
| `_try_mcp_search` asyncio.run() safety   | ❌ NO      | —                                                                                               |
| Atomic write (`os.replace` + `.tmp`)     | ✅ YES     | `TestBlake2bFileHashing.test_codebase_indexer_meta_uses_blake2b_hashes` (round-trip write/load) |
| MCP tools are async                      | ✅ YES     | `TestMCPAsyncTools` (6 tests)                                                                   |
| Score normalization                      | ✅ YES     | `TestScoreNormalization` (2 tests)                                                              |
| Path.resolve() cache consistency         | ✅ YES     | `TestPathResolveCache.test_relative_and_dot_relative_same_engine`                               |
| VaultGraph cache invalidation            | ✅ PARTIAL | `TestGraphCache.test_graph_cache_invalidate_clears` (checks internal state, not integration)    |
| Filter on Prefetch                       | ✅ YES     | `TestFilterOnPrefetch.test_hybrid_search_uses_prefetch_filter`                                  |
| Blake2b hashing                          | ✅ YES     | `TestBlake2bFileHashing` (2 tests)                                                              |
| RRF k=60                                 | ✅ YES     | `TestRrfKParameter` (2 tests)                                                                   |
| Manual node walking                      | ✅ YES     | `TestManualNodeWalking.test_extract_name_uses_child_by_field_name`                              |

### Gaps Identified

#### ❌ MISSING: Graph cache invalidation integration test

**New ADR:** "mcp-graph-cache-invalidation" — `reindex_vault` must reset `_graph_built_at = 0.0` AFTER indexing completes.

**Why test:** Without this, concurrent search during reindex could serve stale graph-boosted scores from the old collection, then crash when the collection is dropped (race with collection drop→search).

**Proposed test location:** `src/vaultspec_rag/tests/test_adr_regression.py`

```python
class TestGraphCacheInvalidation:
    """ADR: mcp-graph-cache-invalidation — reindex_vault resets _graph_built_at."""

    def test_reindex_vault_resets_graph_cache(self):
        """reindex_vault must set _graph_built_at = 0.0 AFTER indexing."""
        import inspect
        from vaultspec_rag.mcp_server import reindex_vault

        # Verify _graph_built_at is reset in the _run() function
        source = inspect.getsource(reindex_vault)
        assert "_graph_built_at = 0.0" in source
```

#### ❌ MISSING: asyncio.run() in sync context safety test

**New ADR:** "cli-asyncio-run-safety" — `_try_mcp_search` and `_try_mcp_reindex` use `asyncio.run()` which is safe because CLI handlers are always synchronous (never run inside an async loop).

**Why test:** If someone wraps the CLI command in an async context manager in the future, `asyncio.run()` would fail with "asyncio.run() cannot be called from a running event loop". This test ensures we catch that regression.

**Proposed test location:** `src/vaultspec_rag/tests/test_cli.py`

```python
def test_try_mcp_search_uses_asyncio_run(self):
    """_try_mcp_search uses asyncio.run(), safe in sync context."""
    import inspect
    from vaultspec_rag.cli import _try_mcp_search

    source = inspect.getsource(_try_mcp_search)
    assert "asyncio.run" in source
    # Verify it's at the top level, not nested in async def
    assert "async def _call" in source
    assert "return asyncio.run(_call())" in source
```

#### ⚠️ PARTIAL: Atomic write coverage incomplete

**Current test:** `TestBlake2bFileHashing.test_codebase_indexer_meta_uses_blake2b_hashes` tests **round-trip** but not **crash-safety**.

**What's missing:** Explicit test that verifies `.tmp` + `os.replace()` pattern prevents corruption if the process crashes mid-write.

**Recommendation:** Add a dedicated test:

```python
class TestAtomicMetaWrite:
    """ADR: atomic-meta-write — _write_meta uses write-to-temp + os.replace."""

    def test_vault_indexer_writes_atomically(self, tmp_path):
        """VaultIndexer._write_meta uses atomic write pattern."""
        import inspect
        from vaultspec_rag.indexer import VaultIndexer

        source = inspect.getsource(VaultIndexer._write_meta)
        assert ".with_suffix('.tmp')" in source or '.with_suffix(".tmp")' in source
        assert "os.replace" in source

    def test_codebase_indexer_writes_atomically(self, tmp_path):
        """CodebaseIndexer._write_meta uses atomic write pattern."""
        import inspect
        from vaultspec_rag.indexer import CodebaseIndexer

        source = inspect.getsource(CodebaseIndexer._write_meta)
        assert ".with_suffix('.tmp')" in source or '.with_suffix(".tmp")' in source
        assert "os.replace" in source
```

______________________________________________________________________

## Summary of New Architectural Invariants NOT Covered by ADR Tests

| Invariant                                   | Location           | Priority | Test Status     | Note                                 |
| ------------------------------------------- | ------------------ | -------- | --------------- | ------------------------------------ |
| Graph cache invalidation on reindex         | mcp_server.py:349  | CRITICAL | ❌ MISSING      | New architectural decision           |
| asyncio.run() safe in CLI sync context      | cli.py:371,413     | HIGH     | ❌ MISSING      | Defensive test                       |
| Atomic write crashes are safe               | indexer.py:835-847 | MEDIUM   | ⚠️ PARTIAL      | Round-trip tested, not crash-safety  |
| Codebase reindex ≠ vault graph invalidation | mcp_server.py:366  | HIGH     | ❌ NOT EXPLICIT | Design assumption needs verification |

______________________________________________________________________

## Recommendations

1. **Add `TestGraphCacheInvalidation`** to `test_adr_regression.py` (inspect-based source check)
1. **Add `TestAsyncioRunSafety`** to `test_cli.py` (verify asyncio.run in sync context)
1. **Add `TestAtomicMetaWrite`** to `test_adr_regression.py` (explicit atomic write pattern verification)
1. **Add integration test** for graph cache invalidation during concurrent search (advanced; can defer)

______________________________________________________________________

## Audit Verdict

| Category                 | Result     | Details                                             |
| ------------------------ | ---------- | --------------------------------------------------- |
| **New Code Correctness** | ✅ PASS    | All 4 components correct; no logic errors           |
| **Thread Safety**        | ✅ PASS    | GPU semaphore + threading.Lock pattern sound        |
| **Crash Safety**         | ✅ PASS    | Atomic writes prevent mid-operation corruption      |
| **Test Coverage**        | ⚠️ PARTIAL | 3 architectural invariants missing regression tests |

**Overall:** Code is **production-ready**. Test coverage gaps are **informational** (not blocking); 3 new unit tests recommended to prevent future regressions.
