# Audit: Indexer Pipeline

Feature: indexer.py document preparation, text splitting, batch indexing

## 2026-03-06 -- Review (Passes 18-25)

### Architecture: SOLID

- `TextSplitter`: Language-specific separators (python, rust, markdown, text)
- `prepare_document()`: Reads file, parses metadata, constructs VaultDocument
- `VaultIndexer`: Full and incremental indexing with mtime-based change detection
- `CodebaseIndexer`: Full codebase indexing via `git ls-files` with chunking
- ThreadPoolExecutor for concurrent I/O during document preparation
- `_save_meta_from_paths()` avoids re-parsing documents for mtime recording

### GPU Pivot Fix: .tolist() on SparseResult (Task #43 -- RESOLVED)

Three sites in indexer.py used `.tolist()` on SparseResult fields:

- Line 301-302 (full_index): FIXED -> `list(svec.indices)`
- Line 395-396 (incremental_index): FIXED -> `list(svec.indices)` (last site fixed)
- Line 585-586 (CodebaseIndexer.full_index): FIXED -> `list(svec.indices)`

### Open Issue

- Task #45 (by proxy): indexer.py:42 docstring says device example "cpu" -- [LOW]

## Pass 27 — Full indexer.py review

Full line-by-line audit. All confirmed correct:

- All 3 `.tolist()` sites fixed (lines 301-302, 393-394, 587-588)
- ThreadPoolExecutor for concurrent I/O in both VaultIndexer and CodebaseIndexer
- `incremental_index()` mtime-based change detection is sound
- `_save_meta_from_paths()` avoids re-parsing documents for mtime recording
- `CodebaseIndexer._scan_codebase()` uses `git ls-files` with `.gitignore` respect
- `TextSplitter` recursive splitting with language-specific separators

No new issues found.
