# Research: watchfiles awatch API Verification — Topic 20

**Date:** 2026-03-09
**Status:** VERIFIED — ALL API CALLS CORRECT
**Confidence:** High (official watchfiles documentation + source code patterns)

## Summary

Verified `src/vaultspec_rag/watcher.py` usage of the watchfiles library. All API calls are correct:

- ✅ `debounce` parameter name and type correct (milliseconds, int, default 1600ms)
- ✅ `stop_event` parameter accepts asyncio.Event (anyio-compatible)
- ✅ `Change` enum used correctly (added=1, modified=2, deleted=3)
- ✅ `watch_filter` callback signature correct

---

## Detailed Findings

### 1. debounce Parameter

**Finding:** ✅ CORRECT

**Current usage** (watcher.py:98):

```python
async for changes in awatch(
    root_dir,
    debounce=debounce,  # User-provided, default 2000ms
    stop_event=stop_event,
    watch_filter=...,
):
```

**Verified API:**

- **Parameter name:** `debounce` (NOT `debounce_threshold`)
- **Type:** `int`
- **Unit:** milliseconds (ms)
- **Default:** 1600ms
- **Purpose:** Maximum time to group changes before yielding them
- **Reference:** [watchfiles API documentation](https://watchfiles.helpmanual.io/api/watch/)

**Assessment:** The code passes `debounce=2000` by default (2000ms = 2 seconds), which is reasonable for a filesystem watcher. This differs from the library default (1600ms) intentionally to reduce re-indexing thrashing.

---

### 2. stop_event Parameter

**Finding:** ✅ CORRECT

**Current usage** (watcher.py:99):

```python
async for changes in awatch(
    root_dir,
    debounce=debounce,
    stop_event=stop_event,  # asyncio.Event type
    watch_filter=...,
):
```

**Verified API:**

- **Parameter name:** `stop_event`
- **Type:** Accepts `anyio.Event` or `asyncio.Event`
- **Semantics:** When set (via `.set()`), stops the async iterator
- **Compatibility:** asyncio.Event works with anyio due to awatch's use of anyio.to_thread.run_sync
- **Reference:** [watchfiles API documentation](https://watchfiles.helpmanual.io/api/watch/)

**Assessment:** The code uses `asyncio.Event` from the caller's async context (see function signature line 67). This is correct because:

1. anyio is compatible with asyncio.Event
2. The event is set gracefully when stopping the watcher
3. No blocking occurs — the async for loop cleanly exits on next yield

---

### 3. Change Enum

**Finding:** ✅ CORRECT

**Current usage** (watcher.py:108-110):

```python
for change_type, path_str in changes:
    path = Path(path_str)
    if change_type in (Change.added, Change.modified, Change.deleted):
```

**Verified API:**

- **Enum type:** IntEnum (integer-backed enumeration)
- **Members:**
  - `Change.added = 1` (new file/directory)
  - `Change.modified = 2` (data or metadata change)
  - `Change.deleted = 3` (removed file/directory)
- **Tuple format:** Each change is `(Change, str)` where str is the path
- **Reference:** [watchfiles PyPI + GitHub issues #275, #148](https://github.com/samuelcolvin/watchfiles)

**Assessment:** The code correctly checks all three change types using enum member comparison. No filtering of change types is done, so all changes (added/modified/deleted) trigger re-indexing logic based on the watch_filter callback.

---

### 4. watch_filter Callback

**Finding:** ✅ CORRECT

**Current usage** (watcher.py:100-103):

```python
watch_filter=lambda _change, path: (
    _is_vault_change(Path(path), vault_dir)
    or _is_code_change(Path(path), root_dir, vault_dir)
),
```

**Verified API:**

- **Parameter:** `watch_filter` (optional callback)
- **Signature:** `Callable[[Change, str], bool]`
- **Return:** `True` to include change, `False` to ignore
- **Purpose:** Pre-filter events before yielding, reducing processing load
- **Reference:** [watchfiles API documentation](https://watchfiles.helpmanual.io/api/watch/)

**Assessment:** The callback correctly:

1. Accepts `_change` (unused) and `path` (str) parameters
2. Returns boolean indicating whether to include the change
3. Avoids processing filesystem noise (e.g., .pyc, **pycache**)
4. Only yields changes matching vault (.md) or code (.py, .rs, etc.) patterns

---

## Round 24 Audit Note

The Round 24 audit flagged uncertainty about the `debounce` parameter name. This has been definitively verified: the parameter is `debounce` (not `debounce_threshold`), and it is in milliseconds, not seconds.

---

## Conclusion

**All watchfiles API usage in watcher.py is correct.** No code changes required. The implementation properly:

- Uses correct parameter names and types
- Passes appropriate default values (debounce=2000ms is intentional)
- Handles asyncio events in an anyio-compatible context
- Filters filesystem events correctly
- Gracefully stops on signal via stop_event

---

## References

- [watchfiles API: watch](https://watchfiles.helpmanual.io/api/watch/)
- [watchfiles PyPI](https://pypi.org/project/watchfiles/)
- [watchfiles GitHub: samuelcolvin/watchfiles](https://github.com/samuelcolvin/watchfiles)
