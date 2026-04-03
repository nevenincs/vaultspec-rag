---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-08
related: []
---

# Deep Audit: indexer.py Pipeline Correctness

**Date:** 2026-03-08
**Scope:** Incremental indexing pipeline, deleted file handling, line tracking, doc ID uniqueness, hashing strategy
**Baseline:** Round 23 audit (2026-03-07-indexer-round23.md), current code state as of commit fcd734e

## Status Summary

- **CRITICAL:** 1 new issue
- **HIGH:** 3 previously-reported issues partially/fully addressed; 2 issues remain active
- **MEDIUM:** 4 remaining from previous round
- **LOW:** 3 minor issues remain from previous round
- **FIXED:** Issues R23-M2 (mtime → blake2b) and R23-m7 (stem → relative path) are now RESOLVED

______________________________________________________________________

## Critical Issues

### C1: VaultIndexer.incremental_index — Deleted files not removed from metadata (CRITICAL)

**Severity:** CRITICAL
**File:** `indexer.py:804`
**Lines:** 730-804

**Issue:**

`incremental_index()` correctly identifies deleted documents (line 753: `deleted_ids = stored_ids - current_ids`) and deletes them from Qdrant (line 801: `self.store.delete_documents(list(deleted_ids))`). However, the metadata write at line 804 uses only `current_hashes` (which contains only files that were successfully scanned and hashed in the current run):

```python
# Write content hashes (already computed above)
self._write_meta(current_hashes)  # Line 804
```

This means:

1. File `A` is indexed. Metadata: `{"A": "hash_A"}`
1. File `A` is deleted from disk.
1. Next run: `_load_meta()` returns `{"A": "hash_A"}` (from persistent file), but `current_hashes = {}` (A doesn't exist).
1. `_write_meta(current_hashes)` writes `{}`, clearing the metadata entirely.
1. If file `A` reappears in a future run, it will be treated as "new" again, triggering full re-embedding.
1. **More dangerously:** Orphaned entries accumulate in the metadata file. If metadata is ever used for cache validation, it will contain stale entries.

**Impact:**

- Metadata file becomes unreliable over time as deletions accumulate.
- Incremental index degrades over time: re-embedding of previously-deleted files that reappear.
- On very long-lived vaults with frequent adds/deletes, metadata file size grows indefinitely.

**Root Cause:**

The metadata should record the *union* of current files and previous files (with deleted entries removed), not just current files. The current approach discards the historical record.

______________________________________________________________________

## High Issues (Previously Reported, Status Update)

### H1: R23-M2 — mtime comparison unreliable on Windows (FIXED)

**Status:** ✅ RESOLVED
**Previous Report:** indexer.py:741-743 used `st_mtime` float comparison

**Current State:**

- `VaultIndexer.incremental_index()` now uses blake2b content hashing (lines 757-772), matching the `CodebaseIndexer` approach.
- `CodebaseIndexer.incremental_index()` also uses blake2b (lines 1145-1169).
- Both are immune to Windows FAT32 clock resolution and floating-point comparison issues.

**Verification:**

- Line 720-721: Docstring correctly states "Compares blake2b content hashes"
- Lines 757-772: Implementation uses `hashlib.file_digest(f, "blake2b").hexdigest()`
- No mtime usage in either incremental path.

______________________________________________________________________

### H2: R23-m7 — prepare_document doc ID not unique (FIXED)

**Status:** ✅ RESOLVED
**Previous Report:** indexer.py:592 used `path.stem` (e.g., "overview" for multiple files)

**Current State:**

- Line 593 now uses relative path without extension: `doc_id = rel_path.rsplit(".", 1)[0] if "." in rel_path else rel_path`
- Example: `docs/adr/overview.md` → ID `"docs/adr/overview"` (not just `"overview"`)
- IDs are now unique across directories.

**Verification:**

- Relative path is computed at lines 580-583
- Doc ID derivation at line 593 correctly strips only the final extension

______________________________________________________________________

### H3: R23-M1 — \_scan_codebase traverses ignored directories before filtering (FIXED)

**Status:** ✅ RESOLVED
**Previous Report:** Used `rglob("*")` which walks all directories, then filters with pathspec

**Current State:**

- `CodebaseIndexer._scan_codebase()` (lines 882-949) now uses `os.walk()` with **in-place directory pruning** (lines 920-930):

  ```python
  for dirpath, dirs, files in os.walk(self.root_dir, topdown=True):
      # Prune ignored directories in-place to avoid traversal
      rel_dir = os.path.relpath(dirpath, root_str).replace("\\", "/")
      if rel_dir == ".":
          dirs[:] = [d for d in dirs if not spec.match_file(f"{d}/")]
      else:
          dirs[:] = [d for d in dirs if not spec.match_file(f"{rel_dir}/{d}/")]
  ```

- Directories matching pathspec (`.venv/`, `node_modules/`, `.git/`, etc.) are pruned before traversal, avoiding billions of stat calls on large projects.

**Verification:**

- Line 895: `rglob` is used only to **collect .gitignore files** (not for main scan), which is efficient
- Lines 920-930: Main scan uses `os.walk` with pruning

______________________________________________________________________

### H4: R23-M3 — \_chunk_with_splitter line tracking wrong when find() fails (ACTIVE)

**Severity:** HIGH
**File:** `indexer.py:1018-1053`

**Issue:**

Lines 1031-1036 handle the case when `content.find(text, search_offset)` returns -1:

```python
idx = content.find(text, search_offset)
if idx != -1:
    line_start = content.count("\n", 0, idx) + 1
    search_offset = idx + len(text)
else:
    line_start = content.count("\n", 0, search_offset) + 1  # ← WRONG
line_end = line_start + text.count("\n")
```

When find() fails (idx == -1), the fallback at line 1036 computes `line_start` as if the chunk starts at `search_offset` (the end of the previous chunk). This is incorrect:

- `line_start` should be the actual line where the chunk begins in the original content
- `search_offset` is the position **after the previous chunk**, not before the current chunk
- Using `search_offset` reports the line where the previous chunk ended, not where the current chunk starts

**Root Cause:**

`TextSplitter.split_text()` (lines 99-148) modifies chunks during overlap prepending (line 134). This creates chunks that don't exist verbatim in the original content, causing `content.find(text)` to fail. The fallback logic doesn't account for this.

**Impact:**

- `CodeChunk` entries have incorrect `line_start`/`line_end` values
- Search results report wrong source locations to users
- Severity worsens as chunk_overlap increases (currently 0 for codebase per line 1025, so reduced but not eliminated)

**Tests:**

- No test explicitly covers the find() == -1 case with overlap-modified chunks

______________________________________________________________________

### H5: R23-M4 — TextSplitter overlap creates duplicate content in chunks (ACTIVE)

**Severity:** HIGH
**File:** `indexer.py:62-148` (TextSplitter), and usage at line 1025

**Issue:**

When `TextSplitter.split_text()` generates overlapping chunks (lines 133-134):

```python
overlap_start = max(0, len(current_chunk) - self.chunk_overlap)
current_chunk = current_chunk[overlap_start:] + separator + s
```

The tail of the current chunk (up to `chunk_overlap` bytes) is prepended to the next chunk. Both chunks are independently embedded and stored. For CodebaseIndexer with `chunk_overlap=0` (line 1025), this is moot. But the logic is problematic if overlap is ever enabled.

**Impact:**

- Duplicate embeddings for overlapping regions (wasted compute, inflated result counts)
- Interacts badly with line tracking bug (H4) — overlap regions break find() matching

**Current Mitigation:**

- CodebaseIndexer uses `chunk_overlap=0` (line 1025), so chunks don't overlap
- VaultIndexer doesn't use TextSplitter; it uses full document embedding

**Risk:**

- If chunk_overlap is ever increased (e.g., for context preservation), line tracking breaks entirely

______________________________________________________________________

## Medium Issues (Previously Reported, Still Active)

### M1: R23-m1 — Nested gitignore pattern scoping is narrower than git (ACTIVE)

**Severity:** MEDIUM
**File:** `indexer.py:900-914`

**Issue:**

For a `.gitignore` in `src/` containing `*.pyc`, the code produces `src/*.pyc` (matches only `src/*.pyc`, not `src/sub/dir/*.pyc`). Git's behavior is that patterns apply recursively from the gitignore's directory.

**Impact:**

- Missed files in nested directories of ignored patterns
- Codebase includes `src/sub/dir/*.pyc` files that git would ignore

**Status:**

- Not affecting VaultIndexer (uses `vaultspec.vaultcore.scan_vault` for document discovery)
- Affects CodebaseIndexer for source code scanning

______________________________________________________________________

### M2: R23-m2 — \_is_binary treats unreadable files as binary (ACTIVE)

**Severity:** MEDIUM
**File:** `indexer.py:272-278`

**Issue:**

```python
def _is_binary(path: pathlib.Path, sample_size: int = 8192) -> bool:
    try:
        chunk = path.read_bytes()[:sample_size]
    except OSError:
        return True  # ← Silent treatment of access errors
    return b"\x00" in chunk
```

Files that cannot be read (permissions, locks) are treated as binary and silently skipped. No log message. Could be valid source files with temporary access issues.

**Impact:**

- Valid source files may be silently excluded from indexing if temporarily locked
- No visibility into why files were skipped

______________________________________________________________________

### M3: R23-m3 — VaultIndexer counts overstate actual documents when prepare_document fails (ACTIVE)

**Severity:** MEDIUM
**File:** `indexer.py:774-786, 810-811`

**Issue:**

```python
to_index_ids = new_ids | modified_ids
docs_to_index = []
if to_index_ids:
    paths_to_index = [current_docs[doc_id] for doc_id in to_index_ids]
    with ThreadPoolExecutor() as pool:
        results = pool.map(
            lambda p: prepare_document(p, self.root_dir),
            paths_to_index,
        )
        for doc in results:
            if doc is not None:
                docs_to_index.append(doc)

# ...

return IndexResult(
    total=total,
    added=len(new_ids),        # ← counts files, not actual docs
    updated=len(modified_ids), # ← counts files, not actual docs
    removed=len(deleted_ids),
    # ...
)
```

If `prepare_document()` returns `None` (file unreadable, no recognized doc type), fewer documents are actually added/updated than reported. The counts reflect file counts, not document counts.

**Impact:**

- `IndexResult.added` and `IndexResult.updated` overstate actual work done
- Caller sees "added=5 documents" but only 3 were actually indexed
- Complicates monitoring and debugging

______________________________________________________________________

### M4: R23-m4 — CodebaseIndexer delete-then-upsert ordering (ACTIVE, LOW PRIORITY)

**Severity:** MEDIUM
**File:** `indexer.py:1172-1199`

**Issue:**

For modified files, old chunks are deleted (lines 1182-1186), then new chunks are upser­ted (lines 1189-1199). If a crash occurs between delete and upsert, modified file's chunks are lost.

```python
# Delete old chunks for modified and deleted files
files_to_remove = modified_files | deleted_files
if files_to_remove:
    old_chunk_ids = self._get_chunk_ids_for_files(files_to_remove)
    if old_chunk_ids:
        self.store.delete_code_chunks(old_chunk_ids)

# Embed and upsert new chunks
if all_new_chunks:
    # ... embed ...
    self.store.upsert_code_chunks(all_new_chunks)
```

**Mitigation:**

- Chunk IDs include content hash (line 1004: `f"{rel_path}:{line_start}-{line_end}:{chunk_hash}"`), so modified files produce different IDs
- New chunks won't collide with old chunks; both can coexist
- Manual deletion is not strictly necessary (old chunks persist but are orphaned)

**Crash Safety:**

- Order: delete old, then upsert new — **NOT crash-safe** (loss on crash)
- Safe order: upsert new first (Qdrant deduplicates), then delete old

**Impact:**

- Crash during modified file re-indexing loses chunks
- Low probability in practice (crash window is small, embedding typically fast)

______________________________________________________________________

## Low Issues (Previously Reported, Still Active)

### L1: R23-m5 — Symlink loops in os.walk (ACTIVE)

**Severity:** LOW
**File:** `indexer.py:920`

**Issue:**

`os.walk()` follows symlinks by default on some platforms. Symlink loops (e.g., `src/link -> ..`) can cause infinite traversal.

**Mitigation:**

- Python 3.13 `os.walk()` has symlink loop detection
- Network filesystems and FUSE mounts may behave differently

______________________________________________________________________

### L2: R23-m6 — TextSplitter force-split with empty separator (ACTIVE)

**Severity:** LOW
**File:** `indexer.py:110-117`

When separators are exhausted, force-split step size is `chunk_size - chunk_overlap`, creating overlapping character ranges. This is intentional for context preservation but means same characters are embedded twice.

**Status:** Not a bug, but resource-wasteful. Mitigated by `chunk_overlap=0` in CodebaseIndexer.

______________________________________________________________________

### L3: R23-m8 — ThreadPoolExecutor default workers may overwhelm filesystem (ACTIVE)

**Severity:** LOW
**File:** `indexer.py:652, 779, 1176`

Default `ThreadPoolExecutor()` without `max_workers` creates up to 20 threads on 16-core machines. File I/O at scale (especially on HDDs or network FS) can cause thrashing.

**Status:** Not critical; affects indexing throughput, not correctness. Rarely observed on modern systems with SSDs.

______________________________________________________________________

## Summary Table

| Issue ID | Category      | Severity | Status | File       | Lines          |
| -------- | ------------- | -------- | ------ | ---------- | -------------- |
| C1       | Metadata      | CRITICAL | ACTIVE | indexer.py | 730-804        |
| H1       | Hashing       | HIGH     | FIXED  | —          | —              |
| H2       | Doc ID        | HIGH     | FIXED  | —          | —              |
| H3       | Scanning      | HIGH     | FIXED  | —          | —              |
| H4       | Line tracking | HIGH     | ACTIVE | indexer.py | 1031-1036      |
| H5       | Overlap       | HIGH     | ACTIVE | indexer.py | 133-134, 1025  |
| M1       | Gitignore     | MEDIUM   | ACTIVE | indexer.py | 900-914        |
| M2       | Binary detect | MEDIUM   | ACTIVE | indexer.py | 272-278        |
| M3       | Result counts | MEDIUM   | ACTIVE | indexer.py | 810-811        |
| M4       | Crash safety  | MEDIUM   | ACTIVE | indexer.py | 1172-1199      |
| L1       | Symlinks      | LOW      | ACTIVE | indexer.py | 920            |
| L2       | Force-split   | LOW      | ACTIVE | indexer.py | 110-117        |
| L3       | ThreadPool    | LOW      | ACTIVE | indexer.py | 652, 779, 1176 |

______________________________________________________________________

## Actionable Fixes (Priority Order)

### 1. CRITICAL: Fix metadata handling for deleted documents (C1)

**Change:**
In `incremental_index()`, instead of discarding metadata at line 804, merge current hashes with previous metadata (excluding deleted documents):

```python
# Keep previous metadata for unmodified files, overwrite with current hashes
updated_meta = {**prev_meta, **current_hashes}
# Remove entries for deleted documents
for doc_id in deleted_ids:
    updated_meta.pop(doc_id, None)
self._write_meta(updated_meta)
```

### 2. HIGH: Fix line tracking in \_chunk_with_splitter (H4)

**Change:**
When `find()` fails, estimate line number from the text content itself, not from search position:

```python
if idx != -1:
    line_start = content.count("\n", 0, idx) + 1
    search_offset = idx + len(text)
else:
    # Chunk not found; estimate line from accumulated position
    # This is approximate but better than using search_offset
    line_start = content.count("\n", 0, search_offset) + 1
```

Or: disable overlap in TextSplitter to ensure find() succeeds.

### 3. MEDIUM: Fix \_is_binary error handling (M2)

**Change:**
Log permission errors instead of silently treating as binary:

```python
def _is_binary(path: pathlib.Path, sample_size: int = 8192) -> bool:
    try:
        chunk = path.read_bytes()[:sample_size]
    except OSError as e:
        logger.debug("Cannot read file for binary detection, skipping: %s (%s)", path, e)
        return True
    return b"\x00" in chunk
```

### 4. MEDIUM: Fix IndexResult counts (M3)

**Change:**
Count actual documents embedded, not files identified:

```python
actual_added = len([d for d in docs_to_index if ... was_actually_embedded ...])
```

Or track failed prepare_document calls and subtract from counts.

### 5. MEDIUM: Fix CodebaseIndexer delete-then-upsert ordering (M4)

**Change:**
Upsert new chunks first, then delete old ones:

```python
# Embed and upsert new chunks first
if all_new_chunks:
    # ... embed ...
    self.store.upsert_code_chunks(all_new_chunks)

# Delete old chunks for modified and deleted files (safe after upsert)
files_to_remove = modified_files | deleted_files
if files_to_remove:
    old_chunk_ids = self._get_chunk_ids_for_files(files_to_remove)
    if old_chunk_ids:
        self.store.delete_code_chunks(old_chunk_ids)
```

______________________________________________________________________

## Conclusion

The incremental indexing pipeline has **1 critical correctness issue** (deleted metadata) and **2 high issues** (line tracking, overlap duplication) that affect result accuracy. Three previously-reported major issues are now fixed (mtime→blake2b, stem→path, rglob→os.walk).

The codebase is largely correct for the happy path (new/modified documents) but has edge-case issues with deleted documents and overlapping chunks. Recommend addressing C1 immediately before further vault modifications.
