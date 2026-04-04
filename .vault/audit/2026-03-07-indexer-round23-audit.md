---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
---

# Round 23 Audit -- indexer.py (deep dive)

Focused on: `_scan_codebase` performance, binary file detection, `TextSplitter` overlap logic, incremental hashing edge cases, remaining bugs. Excludes issues already reported in Round 22 (`docs/audit/2026-03-07-indexer-store-api.md`).

## New findings

### R23-M1: `_scan_codebase` second `rglob("*")` also traverses ignored directories (Major)

Line 903: `self.root_dir.rglob("*")` walks the entire directory tree, entering `.venv/`, `node_modules/`, `.git/`, etc. The pathspec filter (line 909) only rejects matching *files* after they are yielded by rglob. On a typical Node.js project with 50,000+ files in `node_modules/`, this means rglob visits all of them, stats each one, checks extensions, and only then skips via pathspec. The hardcoded exclusion list (lines 872-878) is applied to pathspec *not* to the rglob walk itself.

**Fix:** Use `os.walk` with top-down pruning to skip excluded directories entirely, or at minimum short-circuit files whose relative path starts with an excluded prefix before calling `is_file()`, `stat()`, or `_is_binary()`.

**File:** `indexer.py:903`

### R23-M2: `VaultIndexer.incremental_index` mtime comparison is unreliable on Windows (Major)

Line 741-743: `current_mtime = path.stat().st_mtime` is compared against `prev_mtime = prev_meta.get(doc_id, 0)`. On Windows (FAT32, exFAT), `st_mtime` has only 2-second resolution. If a file is modified within the same 2-second window as the last index run, the mtime will be identical and the change is missed. Additionally, `st_mtime` is a float with platform-dependent precision; floating-point comparison (`>`) can miss changes where the mtime differs by less than the float epsilon.

The `CodebaseIndexer` correctly uses SHA-256 content hashing instead of mtime (lines 1100-1105), which is immune to this issue. `VaultIndexer` should do the same.

**File:** `indexer.py:741-743`

### R23-M3: `_chunk_with_splitter` line tracking produces wrong line numbers when `content.find()` fails (Major)

Lines 998-1003: When `content.find(text, search_offset)` returns -1 (chunk not found in original content), the fallback on line 1003 computes `line_start = content.count("\n", 0, search_offset) + 1`. This uses the *previous* chunk's end position as the line start for the current chunk, which is wrong -- it reports the line where the previous chunk ended, not where this chunk actually is.

This happens when `TextSplitter` modifies chunk content (overlap prepending on line 134 adds text from the previous chunk, making the concatenated string unfindable in the original content). The resulting `CodeChunk` will have incorrect `line_start` and `line_end`, leading to wrong source locations in search results.

**File:** `indexer.py:998-1004`

### R23-M4: `TextSplitter` overlap creates duplicate content across chunks (Major)

Lines 133-134: When a chunk overflows, the overlap logic copies the tail of the current chunk and prepends it to the next:

```python
overlap_start = max(0, len(current_chunk) - self.chunk_overlap)
current_chunk = current_chunk[overlap_start:] + separator + s
```

This means up to `chunk_overlap` (50) characters from chunk N appear verbatim at the start of chunk N+1. Both chunks are independently embedded and stored. When a user searches for text in the overlap region, both chunks match, inflating result count and wasting embedding compute. More critically, the overlap text is not accounted for in the `line_start`/`line_end` tracking in `_chunk_with_splitter`, causing the line number issue described in R23-M3.

**File:** `indexer.py:133-134`

### R23-m1: `_scan_codebase` gitignore pattern scoping is wrong for nested gitignores (Minor)

Lines 884-898: For a `.gitignore` in a subdirectory like `src/.gitignore` containing `*.pyc`, the code produces the pattern `src/*.pyc`. However, git's actual behavior is that patterns in `src/.gitignore` apply relative to `src/` and match recursively (equivalent to `src/**/*.pyc`). The current code only matches `*.pyc` files directly in `src/`, not in `src/sub/dir/*.pyc`. This means nested gitignore rules are narrower than git's actual behavior.

**File:** `indexer.py:884-898`

### R23-m2: `_is_binary` treats files it cannot read as binary (Minor)

Lines 274-278: If `path.read_bytes()` raises `OSError` (permission denied, file locked), the function returns `True`, treating the file as binary and silently skipping it. There is no log message. The file could be a valid source file that is temporarily locked. Combined with the fact that `_scan_codebase` already catches `st_size > _MAX_FILE_SIZE`, the OSError here is likely a genuine access issue, but it should be logged.

**File:** `indexer.py:274-278`

### R23-m3: `VaultIndexer.incremental_index` counts differ from actual changes when `prepare_document` returns None (Minor)

Lines 782-784: `added=len(new_ids)` and `updated=len(modified_ids)` report the number of *files* identified as new/modified. But if `prepare_document` returns `None` for some of these (line 757), fewer documents are actually indexed. The reported counts overstate what was actually added/updated.

**File:** `indexer.py:747-758, 782-784`

### R23-m4: `CodebaseIndexer.incremental_index` deletes old chunks before upserting new ones -- ordering issue (Minor)

Lines 1134-1152: For modified files, old chunks are deleted (line 1139), then new chunks are embedded and upserted (lines 1142-1152). If the process crashes between delete and upsert, the modified file's chunks are lost. Safer order: upsert new chunks first (Qdrant deduplicates by point ID), then delete old chunk IDs that are not in the new set.

However, chunk IDs include a content hash (`rel_path:line_start-line_end:hash`), so modified files produce different chunk IDs. The old IDs must be deleted regardless. The current ordering is acceptable but not crash-safe.

**File:** `indexer.py:1134-1152`

### R23-m5: `_scan_codebase` does not handle symlink loops (Minor)

Line 903: `self.root_dir.rglob("*")` follows symlinks by default on some platforms. A symlink loop (e.g., `src/link -> ..`) would cause infinite traversal. Python 3.13 `rglob` should handle this, but on network filesystems or FUSE mounts, behavior may differ.

**File:** `indexer.py:903`

### R23-m6: `TextSplitter` force-split with empty separator produces overlapping character ranges (Minor)

Lines 110-117: When `seps` is exhausted (last separator is `""`), `remaining_text.split("")` raises `ValueError` in Python (cannot split on empty string). The code reaches the force-split branch at lines 112-117 instead. However, the force-split step size is `self.chunk_size - self.chunk_overlap` = `512 - 50 = 462`. This means consecutive chunks overlap by 50 characters. This is intentional for text continuity but means the same 50 characters are embedded twice, similar to R23-M4.

**File:** `indexer.py:110-117`

### R23-m7: `prepare_document` uses `path.stem` as document ID -- not unique for files in different directories (Minor)

Line 592: `id=path.stem` means two files like `docs/adr/overview.md` and `docs/research/overview.md` both get ID `"overview"`. The second one silently overwrites the first in the store (same `_stable_id` hash). `scan_vault` may return both paths, but only one will survive in Qdrant.

**File:** `indexer.py:592`

### R23-m8: `ThreadPoolExecutor` default thread count may overwhelm the filesystem (Minor)

Lines 646, 751, 1036, 1129: `ThreadPoolExecutor()` without `max_workers` defaults to `min(32, os.cpu_count() + 4)` in Python 3.13. On a 16-core machine this creates 20 threads all doing file I/O simultaneously. On HDDs or network filesystems, this can cause thrashing. For file I/O workloads, 4-8 threads is usually optimal.

**File:** `indexer.py:646, 751, 1036, 1129`
