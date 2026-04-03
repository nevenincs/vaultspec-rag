---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
related: []
---

# Pending Task Verification — 2026-03-07

Verified each pending task description against current source code.

______________________________________________________________________

## Task #82: [CRITICAL] get_code_file symlink traversal bypass (R21-C1)

**Task status:** pending

**Task description accuracy:** PARTIALLY STALE

The task description references `line 202-203` and says `get_code_file` returns error strings. Current code at `mcp_server.py:224-239`:

```python
@mcp.tool()
def get_code_file(path: str) -> str:
    comp = get_comp()
    root_resolved = comp.root_dir.resolve()
    full_path = (root_resolved / path).resolve()
    if not full_path.is_relative_to(root_resolved):
        raise ValueError(f"path '{path}' is outside the workspace")
    if not full_path.exists():
        raise FileNotFoundError(f"File '{path}' not found")
    return full_path.read_text(encoding="utf-8")
```

**Changes since task was written:**

1. **Line numbers shifted** — code is now at lines 224-239, not 202-203.
1. **Error handling fixed** — function now raises `ValueError` and `FileNotFoundError` instead of returning error strings. The R27-M1 finding about error strings has been addressed.
1. **Symlink concern still valid** — the `resolve()` approach still follows symlinks. If `root_dir` itself is a symlink, or if a symlink inside the workspace points outside, the check `is_relative_to(root_resolved)` may pass for paths that traverse symlinks. However, as noted in R21-C1 downgrade (Round 27), this is actually **correct behavior**: `resolve()` on both sides means both are fully canonical. A symlink `workspace/link -> /etc` resolves to `/etc/passwd` which is NOT relative to the resolved root. The traversal check works.

**Verdict:** Task #82 should be **CLOSED or downgraded**. The current implementation correctly handles symlink traversal via `resolve()` on both paths. The only remaining edge case is if `root_dir` itself is a symlink to a parent directory of the attacker-controlled path, which is a misconfiguration, not a code bug.

______________________________________________________________________

## Task #83: [MEDIUM] get_comp() not thread-safe (R21-M7)

**Task status:** pending

**Task description accuracy:** STALE — ALREADY FIXED

Current code at `mcp_server.py:42-83`:

```python
_comp: RagComponents | None = None
_comp_lock = threading.Lock()
_comp_error: Exception | None = None

def get_comp() -> RagComponents:
    global _comp, _comp_error
    if _comp is not None:
        return _comp
    with _comp_lock:
        if _comp is not None:
            return _comp
        if _comp_error is not None:
            raise RuntimeError("RAG initialization previously failed") from _comp_error
        try:
            ...
        except Exception as exc:
            _comp_error = exc
            raise
    return _comp
```

This is **exactly** the fix described in the task. `threading.Lock`, double-checked locking, error caching — all implemented.

**Verdict:** Task #83 should be marked **COMPLETED**. The fix is already in place.

______________________________________________________________________

## Task #84: [MEDIUM] MCP async tools block event loop (R21-M6)

**Task status:** pending (blocked by #83)

**Task description accuracy:** STALE — ALREADY FIXED (but contradicts mcp-sync-tools ADR)

Current code shows all 5 tool functions use `asyncio.to_thread()`:

- `search_vault` (line 136): `async def` + `await asyncio.to_thread(comp.searcher.search_vault, ...)`
- `search_codebase` (line 158): `async def` + `await asyncio.to_thread(comp.searcher.search_codebase, ...)`
- `search_all` (line 198): `async def` + `await asyncio.to_thread(comp.searcher.search_all, ...)`
- `reindex_vault` (line 243): `async def` + `await asyncio.to_thread(comp.vault_indexer.full_index)`
- `reindex_codebase` (line 272): `async def` + `await asyncio.to_thread(...)`

The blocking calls are wrapped in `asyncio.to_thread()` exactly as the task describes.

**However:** The `mcp-sync-tools` ADR says these should be plain `def` (SDK auto-wraps). The current implementation contradicts the ADR by using `async def` + manual `asyncio.to_thread()`. Both approaches achieve the same goal (not blocking the event loop), but the ADR approach is simpler.

**Verdict:** Task #84 should be marked **COMPLETED** (the event-loop-blocking is fixed). A separate task could be created to align with the mcp-sync-tools ADR if desired.

______________________________________________________________________

## Reranker model references (team-lead asked specifically)

The reranker model `cross-encoder/ms-marco-MiniLM-L6-v2` appears in:

| Location    | Line     | Context                                                                     |
| ----------- | -------- | --------------------------------------------------------------------------- |
| `config.py` | 29       | `"reranker_model": "cross-encoder/ms-marco-MiniLM-L6-v2"` (default)         |
| `search.py` | 192      | `self._reranker_model_name: str = cfg.reranker_model` (reads from config)   |
| `search.py` | 211      | `CrossEncoder(self._reranker_model_name, device="cuda")` (loads model)      |
| `CLAUDE.md` | ~line 42 | `CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2", device="cuda")` (docs) |

**If upgrading to bge-reranker-v2-m3:**

1. `config.py:29` — change default model name
1. `CLAUDE.md` — update the reference
1. `search.py` — no code change needed (reads model name from config)
1. **Batch size concern:** `search.py:228-241` `_rerank()` creates `(query, text)` pairs and calls `reranker.predict(pairs)` in one batch. ms-marco-MiniLM-L6-v2 is 22M params; bge-reranker-v2-m3 is 568M params (~25x larger). With `top_k * 4 = 20` pairs per rerank call, this should fit in VRAM, but the larger model will be slower. No batch_size parameter is currently passed to `predict()` — sentence-transformers defaults to reasonable batching internally.
1. **VRAM impact:** Current stack uses ~3GB (Qwen3 + SPLADE). Adding 568M-param reranker in fp16 adds ~1.1GB. Total ~4.1GB. Should fit on 8GB+ GPUs but tight on 6GB.

______________________________________________________________________

## hybrid_search sparse=None handling (team-lead asked specifically)

**Current implementation is correct.** Both `hybrid_search` (store.py:505-584) and `hybrid_search_codebase` (store.py:586-645) already handle `sparse_vector: SparseResult | None = None`:

- Lines 548-559 / 618-629: `if sparse_vector is not None:` — only adds sparse Prefetch when sparse vector provided
- When `sparse_vector is None`, only a dense Prefetch is created, and `FusionQuery(RRF)` runs on a single prefetch (which is valid — Qdrant handles single-prefetch RRF correctly, returning dense-only results)

**No changes needed.** The conditional logic is already in place. If this task was about a bug where sparse=None caused an error, it has been fixed.

______________________________________________________________________

## Summary

| Task | Status in TaskList | Actual Status                                 | Action Needed             |
| ---- | ------------------ | --------------------------------------------- | ------------------------- |
| #82  | pending            | Edge case only, core check correct            | CLOSE or DOWNGRADE to low |
| #83  | pending            | **ALREADY FIXED** in source                   | Mark COMPLETED            |
| #84  | pending            | **ALREADY FIXED** in source (contradicts ADR) | Mark COMPLETED            |
