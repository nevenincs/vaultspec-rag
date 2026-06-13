---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-06
modified: '2026-03-06'
---

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

## 2026-03-06 -- Major Overhaul (Tasks #3, #4, #9)

### Critical Bug Fixes (Task #3 -- RESOLVED)

1. **Line tracking**: `content.find(text)` replaced with offset-tracking.
   Walks forward through chunks from last known offset, preventing
   duplicate code from mapping to the first occurrence's line number.

1. **Chunk ID collisions**: IDs now include 12-char SHA256 content hash:
   `{rel_path}:{line_start}-{line_end}:{hash}`. Guarantees uniqueness.

1. **CodebaseIndexer.incremental_index()**: New method using SHA256 file
   content hashing (not mtime). Detects new/modified/deleted files, only
   re-embeds changed files. Metadata format: `{rel_path: content_hash}`.

1. **Docstring fix**: device example changed from "cpu" to "cuda" (Task #45 resolved).

### AST Chunking + Pathspec Overhaul (Task #4 -- RESOLVED)

1. **ASTChunker**: New class implementing cAST algorithm (arXiv 2506.15655).
   Depth-first AST traversal, split oversized nodes, merge small siblings.
   Uses `tree-sitter-language-pack` (actively maintained). Falls back to
   `TextSplitter` for data formats (YAML, TOML, JSON, HTML, CSS).

1. **pathspec scanning**: `_scan_codebase()` now uses `pathspec.GitIgnoreSpec`
   instead of `git ls-files` + `rglob("*")`. Collects patterns from all
   `.gitignore` files at every directory level. No subprocess dependency.

1. **Language support expanded**: 7 -> 25 extensions. Added Go, Java, C,
   C++, C#, Ruby, Shell/Bash, YAML, TOML, JSON, HTML, CSS, Kotlin.
   `LANGUAGE_MAP` dict maps extensions to `(language, grammar)` tuples.

1. **Safety guards**: `_is_binary()` (null byte detection), `_MAX_FILE_SIZE`
   (10MB limit). Applied during scanning before any file is read.

1. **Dependencies added**: `tree-sitter>=0.23`, `tree-sitter-language-pack>=0.10`,
   `pathspec>=0.12`.

### Unit Tests (Task #9 -- RESOLVED)

22 new unit tests added in `test_indexer_unit.py`:

- ASTChunker: boundary splitting, content coverage, line numbers, empty input,
  multi-language (Python, Rust, JS, Go), force-split large nodes
- LANGUAGE_MAP: extension mapping, count, grammar presence
- Binary detection: text/binary/empty files
- File size limit: 10MB constant
- Chunk ID format: hash presence, uniqueness

All 102 unit tests pass. No open issues.
