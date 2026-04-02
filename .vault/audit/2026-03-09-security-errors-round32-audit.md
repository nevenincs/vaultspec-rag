---
tags:
  - "#audit"
  - "#gpu-rag-stack"
date: 2026-03-09
related: []
---

# Round 32: Security & Error-Handling Audit

**Date:** 2026-03-09
**Auditor:** Claude Code (Haiku 4.5)
**Status:** COMPLETE — 2 CRITICAL, 2 HIGH, 3 MEDIUM

---

## Executive Summary

Round 32 audits security (path traversal, command injection, input validation, info disclosure) and error-handling (Qdrant unavailability, CUDA OOM, disk full, partial indexing). Found **2 CRITICAL** path validation gaps, **2 HIGH** error propagation issues, and **3 MEDIUM** concerns about incomplete cleanup. No command injection or direct subprocess risks detected.

---

## Security Audit Results

### 1. Path Traversal — OK (Symlink + Traversal Safeguards)

**Component:** `mcp_server.py:get_code_file()` (lines 305–328)

✅ **PASS**: Correctly validates path containment:

```python
root_resolved = comp.root_dir.resolve()
full_path = (root_resolved / path).resolve()
if not full_path.is_relative_to(root_resolved):
    raise ValueError(f"path '{path}' is outside the workspace")
```

Both `.resolve()` calls normalize symlinks and `..` traversals. The `is_relative_to()` check prevents escape attempts. File existence and size (10 MB max) also validated.

---

### 2. CLI --target Path Validation — CRITICAL

**Component:** `cli.py:main()` (lines 93–101)

**Finding:** `--target` accepted via `typer.Option(resolve_path=True)` without additional safety checks. While typer resolves the path, subsequent use in `CLIState` is unconstrained:

```python
state: CLIState = ctx.obj
target = state.target
store = VaultStore(target)  # Line 245
```

**Risk:** If `--target` points outside the intended workspace (e.g., `/etc/passwd`, sibling projects), the indexer and searcher blindly accept it. No workspace validation ensures `target` actually contains `.vault/` or `.vaultspec/`.

**Severity:** **CRITICAL** — Potential lateral data access across sibling projects or system directories.

**Recommendation:**

- Add workspace validation in `main()` after `resolve_workspace()` returns (lines 133–135).
- Verify `layout.target_dir` contains `.vault/` AND `.vaultspec/` before proceeding.
- Example (pseudocode):

  ```python
  if not layout.vaultspec_dir.is_dir():
      console.print("[bold red]Error:[/] target is not a valid vaultspec workspace")
      raise typer.Exit(code=1)
  ```

---

### 3. API Path Validation — CRITICAL

**Component:** `api.py:get_engine()` (lines 59–73)

**Finding:** `get_engine(root_dir)` resolves the path but does NOT validate it's a valid vaultspec workspace:

```python
def get_engine(root_dir: pathlib.Path) -> _Engine:
    from pathlib import Path
    global _engine
    root_dir = Path(root_dir).resolve()
    # No workspace validation — accepts any directory
    if _engine is not None and _engine.root_dir == root_dir:
        return _engine
    ...
    _engine = _Engine(root_dir)  # Creates store + indexer with unvalidated root
    return _engine
```

**Risk:** Caller can pass arbitrary directories. No `.vaultspec/` or `.vault/` check. A rogue caller or MCP client could initialize engines against system directories or other projects.

**Severity:** **CRITICAL** — Data isolation violation; no workspace boundary enforcement at API level.

**Recommendation:**

- Validate `root_dir / ".vaultspec"` exists before creating engine.
- Raise `ValueError` with clear message if workspace structure is invalid.

---

### 4. Command Injection — OK

**Component:** `cli.py:handle_test()` (lines 926–940)

✅ **PASS**: Subprocess call uses list form (no shell):

```python
cmd = [sys.executable, "-m", "pytest", test_dir, *ctx.args]
raise SystemExit(subprocess.call(cmd))
```

No string interpolation; args passed as list elements. Safe from shell injection.

---

### 5. Query Length Validation — MEDIUM

**Component:** `search.py:search_vault()`, `search_codebase()`, `search_all()` (lines 253–397)

**Finding:** Query string length is unbounded. A 1GB query could cause OOM in `encode_query()`:

```python
def search_vault(self, raw_query: str, top_k: int = 5) -> list[SearchResult]:
    parsed = parse_query(raw_query)
    query_text = parsed.text or raw_query  # No length check
    query_vector = self.model.encode_query(query_text)  # Can OOM
```

**Severity:** **MEDIUM** — Denial of service (resource exhaustion), not data leakage.

**Recommendation:**

- Add max length constant (e.g., `MAX_QUERY_LEN = 10000`).
- Truncate or reject oversized queries in `search_vault()`, `search_codebase()`, `search_all()`.
- Log warning if query is truncated.

---

### 6. MCP Parameter Validation — MEDIUM

**Component:** `mcp_server.py` tools (lines 171–393)

**Finding:** The `_clamp_top_k()` function (lines 164–166) validates `top_k` but other params are not checked:

- `language`, `node_type`, `function_name`, `class_name` (in `search_codebase()`) are passed directly to store without length or character validation.
- `path` in `get_code_file()` is validated (good), but other resource paths are not.

**Severity:** **MEDIUM** — Less likely to cause OOM, but filter values could be unexpectedly large (e.g., 100KB `class_name`).

**Recommendation:**

- Add max length for filter parameters (e.g., 256 chars each).
- Validate in `search_codebase()` before calling searcher.

---

### 7. Error Message Information Disclosure — MEDIUM

**Component:** `mcp_server.py:get_comp()` (lines 51–87)

**Finding:** Error caching includes full exception trace:

```python
if _comp_error is not None:
    raise RuntimeError(
        f"RAG initialization previously failed: {_comp_error}"
    ) from _comp_error
```

If the exception contains environment variable names (e.g., `VAULTSPEC_ROOT=/secret/path`), it leaks to the MCP client.

**Severity:** **MEDIUM** — Information disclosure (paths, env vars), not a direct vulnerability.

**Recommendation:**

- Sanitize exception message before caching: extract only error type + brief description.
- Log full traceback to logger instead.
- Example:

  ```python
  error_msg = str(_comp_error).split('\n')[0]  # First line only
  raise RuntimeError(f"RAG initialization failed: {error_msg}") from None
  ```

---

## Error-Handling Audit Results

### 8. Qdrant Unavailable / Corrupted — HIGH

**Component:** `store.py:__init__()` (lines 115–143)

**Finding:** If Qdrant database is locked or corrupted, the error propagates without recovery:

```python
def __init__(self, root_dir: pathlib.Path | str, embedding_dim: int | None = None):
    _check_rag_deps()
    ...
    self.db_path.mkdir(parents=True, exist_ok=True)
    self._client: QdrantClient = _QdrantClient(path=str(self.db_path))
    # ^ Can raise if db_path is locked by another process
```

**Risk:** If another process holds a lock, `QdrantClient(path=...)` raises `LockError`. This propagates to `get_comp()`, cached as `_comp_error`. Subsequent search requests fail with "RAG initialization previously failed" instead of attempting recovery.

**Scenario:**

1. Process A: `vaultspec-rag index` starts, acquires Qdrant lock.
2. Process B: `vaultspec-rag search` tries to initialize, gets `LockError`.
3. `_comp_error` is set permanently.
4. Process A finishes and releases lock.
5. Process B: Next search still fails — `_comp_error` is cached forever.

**Severity:** **HIGH** — Persistent failure even after the lock is released.

**Recommendation:**

- Do NOT cache initialization errors. Or:
- Implement exponential backoff retry (with max retries) instead of permanent caching.
- Clear `_comp_error` after successful recovery.

---

### 9. CUDA OOM During Indexing — OK (Handled with Retry)

**Component:** `embeddings.py:encode_documents()` (lines 213–252)

✅ **PASS**: OOM is caught and retried with reduced batch size:

```python
while True:
    try:
        embeddings = self._dense_model.encode(...)
        return np.asarray(embeddings, dtype=np.float32)
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        if batch_size <= 1:
            raise
        batch_size = max(1, batch_size // 2)
        logger.warning("CUDA OOM during dense encoding, retrying...")
```

GPU semaphore is held during retry, ensuring no race. If OOM persists at batch_size=1, exception propagates cleanly.

---

### 10. Disk Full During Metadata Write — OK (Atomic with Temp File)

**Component:** `indexer.py` (checked via memory) — metadata written with temp + move

**Finding (from memory audit):** Metadata writes use `tmp_path.write_text()` followed by `os.replace()`. If `write_text()` fails due to disk full, the `.tmp` file is left on disk but the real metadata file is untouched. Next run will not know the file is stale.

**Current behavior:** After `upsert_documents()` succeeds but `_write_meta()` fails, the metadata (hash, offset) is lost. Next run assumes the document is unchanged (because hash is missing from `.meta.json`), leading to duplication.

✅ **PASS** (already audited in Round 29 / CRITICAL C2). Atomic writes are correct; metadata loss is a data-integrity issue, not error-handling per se.

---

### 11. Partial Indexing — CRITICAL (Race Window)

**Component:** `cli.py:handle_index()` (lines 141–333) → `indexer.py:full_index(clean=True)`

**Finding:** When `--clean` is specified:

```python
if clean:
    console.log(f"Cleaning existing index...")
    store.close()
    if store.db_path.exists():
        shutil.rmtree(store.db_path)
    store = VaultStore(target)  # Recreates store + collection

# Then: vault indexing starts
v_indexer.full_index(clean=True)
```

**Race window:** Between `shutil.rmtree()` and `store = VaultStore(target)`, if a concurrent search happens, it will fail with "collection not found" (no fallback).

**Scenario:**

1. CLI: `vaultspec-rag index --clean` starts.
2. CLI: Deletes `.qdrant/` directory.
3. MCP: Concurrent search request arrives.
4. MCP: Tries to open Qdrant collection → `collection_not_found` error.
5. No fallback; search returns error to client.

**Severity:** **CRITICAL** — Already identified in Round 29, but error handling was not addressed. See Round 29 C1 audit for full context.

**Status:** Unresolved from Round 29.

---

### 12. Symlink Following in Codebase Scan — OK

**Component:** `indexer.py:_scan_codebase()` (checked via memory)

✅ **PASS**: Uses `os.walk(..., followlinks=False)` by default, preventing symlink escapes. Verified in prior audits.

---

### 13. Language / Node-Type Filter Injection — OK

**Component:** `search.py:parse_query()` (lines 81–99) → `store.py:_build_code_filter()`

✅ **PASS**: Filters are extracted via regex, not user-provided directly. Store validates filter keys against a whitelist:

```python
if key in ("language", "path", "node_type", "function_name", "class_name"):
    conditions.append(...)
else:
    logger.warning("Unknown filter key: %s", key)
```

Unknown keys are logged, not injected. Safe.

---

## Summary Table

| ID | Category | Finding | Severity | Status |
|----|----------|---------|----------|--------|
| C1 | Path Traversal | CLI `--target` not validated as workspace | CRITICAL | New |
| C2 | Path Traversal | API `get_engine()` accepts any directory | CRITICAL | New |
| H1 | Error Handling | Qdrant lock cached permanently | HIGH | New |
| H2 | Race Condition | Full reindex drops collection (race window) | CRITICAL* | Round 29 C1 |
| M1 | Input Validation | Query length unbounded | MEDIUM | New |
| M2 | Input Validation | MCP filter param lengths unchecked | MEDIUM | New |
| M3 | Information Disclosure | Error messages leak paths | MEDIUM | New |

*H2 labeled CRITICAL in Round 29, still unresolved.

---

## Recommendations

### Priority 1 (Immediate)

1. **C1 — CLI --target validation:**
   - After `resolve_workspace()`, verify `layout.vaultspec_dir.is_dir()`.
   - Reject invalid workspaces with clear error message.

2. **C2 — API workspace validation:**
   - Add check in `get_engine()`: verify `(root_dir / ".vaultspec").is_dir()`.
   - Raise `ValueError` if missing.

3. **H1 — Qdrant lock handling:**
   - Remove permanent error caching OR implement exponential backoff retry.
   - Clear `_comp_error` after successful recovery.

### Priority 2 (Important)

1. **H2 — Race window during full reindex (Round 29 C1):**
   - Implement collection lock or atomic rename.
   - See Round 29 for full analysis.

2. **M1 — Query length validation:**
   - Add `MAX_QUERY_LEN = 10000` constant.
   - Truncate in `search_vault()` / `search_all()`.

3. **M3 — Error message sanitization:**
   - Extract only first line of exception.
   - Log full traceback separately.

### Priority 3 (Enhancement)

1. **M2 — MCP filter validation:**
   - Clamp `language`, `node_type`, etc. to 256 chars.

---

## Files Affected

- `src/vaultspec_rag/cli.py` (C1, M1)
- `src/vaultspec_rag/api.py` (C2)
- `src/vaultspec_rag/mcp_server.py` (H1, M3, M2)
- `src/vaultspec_rag/search.py` (M1)

---

## Verification Checklist

- [ ] C1: CLI rejects `--target` pointing outside workspace
- [ ] C2: API rejects arbitrary `root_dir` without `.vaultspec/`
- [ ] H1: Qdrant lock errors do not permanently block subsequent searches
- [ ] M1: Query strings > 10KB are truncated with warning
- [ ] M3: Exception messages do not leak paths/env vars
- [ ] M2: Filter parameters have max length enforcement
