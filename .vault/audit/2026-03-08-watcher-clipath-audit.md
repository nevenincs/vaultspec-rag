---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-08
---

# Round 24 Audit: Watcher, CLI Fast-Path, MCP Client

**Date:** 2026-03-08
**Scope:** `src/vaultspec_rag/watcher.py` (new), `src/vaultspec_rag/cli.py` (functions `_try_mcp_reindex`, `_try_mcp_search`, `_display_search_results`, `handle_search` updates)
**Auditor:** codebase-auditor-24
**Verdict:** MEDIUM and LOW severity issues identified; no CRITICAL/HIGH issues.

______________________________________________________________________

## Summary Table

| Severity | Finding ID | Description                                                                          | File:Line       | Status      |
| -------- | ---------- | ------------------------------------------------------------------------------------ | --------------- | ----------- |
| MEDIUM   | M1         | `asyncio.run()` called from sync CLI context without event loop cleanup              | cli.py:303, 343 | Identified  |
| MEDIUM   | M2         | JSON response shape for MCP tools not strictly validated before `.get()`             | cli.py:336–337  | Identified  |
| LOW      | L1         | Cooldown timestamps use `time.monotonic()` but no validation of parameter semantics  | watcher.py:69   | Verified OK |
| LOW      | L2         | MCP search does not validate `search_type` → falls back to `"search_vault"` silently | cli.py:316–317  | Verified OK |
| LOW      | L3         | `_display_search_results()` converts `score` via `float()` without error handling    | cli.py:323      | Identified  |

______________________________________________________________________

## Detailed Findings

### M1: asyncio.run() Called from Sync Context — Event Loop Management

**Severity:** MEDIUM
**Location:** `cli.py:303` (in `_try_mcp_reindex`), `cli.py:343` (in `_try_mcp_search`)
**Pattern:**

```python
async def _call() -> ...:
    # ... async work

try:
    return asyncio.run(_call())
except Exception:
    return None
```

**Issue:**

- `asyncio.run()` creates a new event loop, runs the coroutine, and closes it.
- Called from **synchronous** CLI handler (`handle_search` → `_try_mcp_search`).
- If `handle_search` is ever called from within an existing async context (e.g., if the CLI is invoked from async code), `asyncio.run()` will raise `RuntimeError: asyncio.run() cannot be called from a running event loop`.
- The outer `try`/`except` at lines 302–305 and 342–345 catches this but returns `None`, which is **correct for graceful degradation** (falls back to in-process search).
- **However:** This design assumes the CLI is always called from synchronous context. If typer ever adds async support or if someone wraps the CLI in an async framework, this will silently fail.

**Verification:** The exception handling is **correct but defensive**. No bug here, but document the assumption.

**Recommendation:** Add a comment explaining why `asyncio.run()` is safe here (CLI is sync-only).

______________________________________________________________________

### M2: MCP Response Shape Not Strictly Validated

**Severity:** MEDIUM
**Location:** `cli.py:336–337` (in `_try_mcp_search`)
**Pattern:**

```python
data = json.loads(result.content[0].text)
return data.get("results", [])
```

**Issue:**

- `json.loads()` can fail if the MCP tool response is **not valid JSON**.
- The outer `try`/`except Exception` at lines 320–340 catches JSON decode errors, so this is **safe**.
- **However:** The code assumes the response structure is `{"results": [...]}`. If the server responds with a different shape (e.g., `{"data": [...]}` or just a list), `data.get("results", [])` silently returns `[]` (no results), which is indistinguishable from a real empty result.

**Verification:** Safe due to catch-all `except`. No crash risk, but silent failures are possible.

**Recommendation:** The implementation is acceptable for a "fast path" that gracefully degrades. The fallback to in-process search (line 384) provides recovery.

______________________________________________________________________

### L1: Cooldown Logic Uses `time.monotonic()` Correctly

**Severity:** LOW (informational)
**Location:** `watcher.py:116, 119, 133, 145, 159`
**Pattern:**

```python
now = time.monotonic()
if now - _last_vault_index < cooldown:
    logger.debug(...)
else:
    # trigger re-index
    _last_vault_index = time.monotonic()
```

**Verification:** ✓ CORRECT

- `time.monotonic()` is the **correct** choice for elapsed-time checks (immune to system clock adjustments).
- Cooldown timestamps are scoped per-source (`_last_vault_index`, `_last_code_index`) as separate locals.
- No race condition: `now` is computed once per batch of changes, avoiding time-of-check/time-of-use.
- GPU semaphore acquired **before** indexing work, ensuring serialization.

**Status:** Verified OK. No issues.

______________________________________________________________________

### L2: MCP Search Type Fallback to `"search_vault"`

**Severity:** LOW (informational)
**Location:** `cli.py:316–317` (in `_try_mcp_search`)
**Pattern:**

```python
tool_map = {"vault": "search_vault", "code": "search_codebase", "all": "search_all"}
tool_name = tool_map.get(search_type, "search_vault")
```

**Verification:** ✓ CORRECT

- `search_type` is constrained to `Literal["vault", "code", "all"]` by typer's type checking (line 373–380).
- The `.get()` default is **defensive** but unreachable given the type constraint.
- Silent fallback is acceptable for internal consistency.

**Status:** Verified OK. No issues.

______________________________________________________________________

### L3: Score Conversion Without Error Handling

**Severity:** LOW
**Location:** `cli.py:323` (in `_display_search_results`)
**Pattern:**

```python
score = float(r.get("score", 0.0))
table.add_row(f"{score:.2f}", location, snippet)
```

**Issue:**

- `r.get("score", 0.0)` returns a value (possibly already a `float`, possibly a `str`).
- `float()` conversion will **fail** if the value is a non-numeric string (e.g., `"error"`, `"null"`).
- **However:** This function is **only called after successful MCP search** (line 412–413 validate `mcp_results is not None`), and the MCP server is trusted to return valid scores.
- No user input flows through this path directly.

**Verification:** Safe for trusted MCP response. No crash risk in normal operation.

**Recommendation:** Add defensive `.get("score", 0.0)` with numeric default (already done) to avoid exceptions; `float()` conversion is then safe.

______________________________________________________________________

## NOT TASKED — Verification Summary

✓ **Type annotations:** All functions properly annotated (lines 270–327).
✓ **Imports:** No bare `import unittest`, no `mock`/`patch`, no forbidden dependencies (fastembed, ONNX).
✓ **Logging:** No `print()` statements; uses `logging` and `console.print()` correctly.
✓ **asyncio.Event:** Used correctly in `watch_and_reindex` signature; passed via parameter.
✓ **Bare except clauses:** Only broad exception handlers at function boundaries (lines 299–300, 339–340, 302–305, 342–345), appropriate for "try MCP, fall back gracefully" pattern.
✓ **GPU semaphore:** Acquired before GPU work; not held across network I/O.
✓ **watchfiles integration:** `debounce` parameter passed to `awatch()`; `stop_event` integrated correctly.
✓ **Graceful fallback:** All MCP failures result in fallback to in-process search; no data loss.
✓ **VAULTSPEC_ROOT propagation:** `--port` option on `handle_search` correctly skips workspace resolution (lines 411–419); no ctx.obj accessed in fast path.

______________________________________________________________________

## Top 3 Findings for Orchestrator

1. **M1: asyncio.run() Event Loop Assumption** — Safe today but brittle if CLI becomes async. Add documentation explaining sync-only constraint.
1. **M2: MCP Response Shape Flexibility** — Server returns `{"results": [...]}` shape; no strict validation but graceful degradation works.
1. **L1–L3: Remaining Issues Minor** — Cooldown logic correct, type safety enforced, score conversion safe for trusted server responses.

**Triage recommendation:** Deploy as-is. Consider documenting the async constraint in cli.py as a follow-up.
