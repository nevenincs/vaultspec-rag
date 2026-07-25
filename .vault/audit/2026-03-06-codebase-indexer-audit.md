---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: '2026-03-06'
modified: '2026-07-25'
related:
  - '[[2026-03-06-gpu-only-rag-stack-adr]]'
---

# CodebaseIndexer Audit — 2026-03-06

## Round 1: Core Implementation

Audited files:

- `src/vaultspec_rag/indexer.py`
- `src/vaultspec_rag/config.py`
- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/search.py`

### CRITICAL Issues

**C1. `content.find(text)` line tracking is silently wrong** (indexer.py:544)
_Known issue #1._ `content.find(text)` returns the first occurrence of the chunk text in the file. If two chunks share identical substrings (common in code — repeated import blocks, blank lines, boilerplate), the wrong position is returned. All subsequent line numbers for that file will be wrong, and since chunk IDs embed line numbers, this cascades into ID collisions (C2).

**C2. Chunk ID collision risk** (indexer.py:550)
_Known issue #2._ Format `{rel_path}:{line_start}-{line_end}` is deterministic but not unique when line tracking is wrong (C1). Two chunks from the same file can get the same start-end range. Qdrant's `_stable_id()` hash will map them to the same point ID, silently overwriting data. Fix: include a content hash or chunk index in the ID.

**C3. Missing `incremental_index()` in CodebaseIndexer** (indexer.py:469-624)
_Known issue #3._ `VaultIndexer` has a full `incremental_index()` implementation (lines 333-413) that compares mtimes and only re-embeds changed files. `CodebaseIndexer` has `_load_meta()` and `_write_meta()` but no `incremental_index()` method — every invocation does a full re-embed of all code files. For large codebases this is extremely expensive on GPU time.

**C4. `_stable_id()` 63-bit hash has non-trivial collision probability** (store.py:580-589)
The hash space is 2^63 (~9.2e18). By the birthday paradox, collision probability reaches 1% at ~430 million documents. While this is unlikely for vault docs (~hundreds), codebase chunks could reach thousands per project. More critically, the truncation to 63 bits (masking with `0x7FFFFFFFFFFFFFFF`) discards half the entropy of SHA-256. If multiple projects share a Qdrant instance, collision risk compounds. Not immediately critical but a design smell.

### MAJOR Issues

**M1. Only 7 file extensions supported** (indexer.py:488-496)
_Known issue #4._ Missing: `.go`, `.java`, `.c`, `.cpp`, `.h`, `.hpp`, `.cs`, `.rb`, `.sh`, `.bash`, `.zsh`, `.yaml`, `.yml`, `.toml`, `.json`, `.html`, `.css`, `.scss`, `.sql`, `.proto`, `.graphql`, `.dockerfile`, `.tf`, `.hcl`. Any project with Go, Java, or C/C++ code is completely invisible to the indexer.

**M2. `git ls-files` fallback ignores .gitignore** (indexer.py:514-515)
_Known issue #5._ When `git ls-files` fails (not a git repo, or git not installed), the fallback `self.root_dir.rglob("*")` returns everything including `.gitignore`d paths. Only `.venv`, `.git`, and `node_modules` are hardcoded exclusions (line 524-526). Build artifacts, `dist/`, `__pycache__/`, `.tox/`, `.mypy_cache/` etc. will all be indexed.

**M3. No binary file detection** (indexer.py:528-559)
_Known issue #6._ `_chunk_file()` calls `path.read_text(encoding="utf-8")` on any file with a supported extension. Binary files with `.js` or `.py` extensions (rare but possible — compiled/minified/bundled) will either raise `UnicodeDecodeError` (caught by the generic `except Exception`) or produce garbage chunks that waste GPU embedding time.

**M4. No file size limit** (indexer.py:528-559)
_Known issue #7._ No guard against indexing huge files. A 50MB generated file or vendor bundle will be read entirely into memory, split into hundreds of chunks, and each chunk embedded on GPU. Should have a configurable max file size (e.g., 10MB default).

**M5. TextSplitter overlap logic creates broken chunks** (indexer.py:125-127)
_Known issue #8._ The overlap implementation on line 126-127 takes the tail of the previous chunk and prepends it to the next split. This breaks syntactic boundaries — a function definition could be sliced mid-statement. The overlap text has no relation to the separator-based split points.

**M6. JS/TS fall through to generic separators** (indexer.py:66-90)
_Known issue #9._ The `separators` dict has entries for `python`, `rust`, `markdown`, and `text`. The `_get_language()` method returns `"javascript"` or `"typescript"` for JS/TS files, but there are no corresponding separator entries. `.get(language, ...)` falls back to `["\n\n", "\n", " ", ""]` — no function/class/method boundary awareness.

**M7. `tag` filter parsed but never reaches Qdrant** (search.py:80-83, store.py:538-555)
`parse_query()` extracts `tag:` filters and stores them as `filters["tag"]`. But `_build_filter()` only handles keys `"date"`, `"doc_type"`, and `"feature"`. The `"tag"` key is silently dropped. Similarly, `search_vault()` (line 229-233) only passes through `doc_type`, `feature`, and `date`. Users who type `tag:#rag` get no filtering — a silent correctness bug.

**M8. `search_all()` double-reranks results** (search.py:303-310)
`search_vault()` already applies CrossEncoder reranking (line 262) and graph reranking (line 264). `search_codebase()` also applies CrossEncoder reranking (line 301). Then `search_all()` combines them and sorts by score. But the vault scores are graph-boosted floats while codebase scores are raw CrossEncoder logits — these are on completely different scales. Sorting them together produces meaningless rankings.

**M9. No config options for CodebaseIndexer** (config.py:23-35)
`rag_defaults` has no codebase-specific config: no `code_chunk_size`, `code_chunk_overlap`, `code_max_file_size`, `code_supported_extensions`, `code_excluded_dirs`. All CodebaseIndexer parameters are hardcoded (chunk_size=512, overlap=50, extensions={7 items}). Users cannot customize without editing source code.

**M10. `CodebaseIndexer.full_index()` has no error handling for failed delete** (indexer.py:592-594)
Unlike `VaultIndexer.full_index()` which catches `OSError` on delete failure and aborts to prevent duplicates (line 307-316), `CodebaseIndexer.full_index()` calls `self.store.delete_code_chunks()` without any error handling. If the delete fails, the subsequent `upsert_code_chunks()` will create duplicates.

### MINOR Issues

**m1. Unused loop variable `_i`** (indexer.py:542)
`for _i, text in enumerate(text_chunks)` — the index `_i` is never used. Could be `for text in text_chunks` directly.

**m2. `_save_meta()` method is unused** (indexer.py:415-429)
`VaultIndexer._save_meta()` accepts a `list[VaultDocument]` and reconstructs paths from `docs_dir / doc.path`. But both `full_index()` and `incremental_index()` call `_save_meta_from_paths()` instead, which takes the original path dict. The `_save_meta()` method is dead code.

**m3. `query_text` parameter marked `noqa: ARG002` in both search methods** (store.py:378, 453)
Both `hybrid_search()` and `hybrid_search_codebase()` accept `query_text: str` but never use it (sparse vector is passed separately). The parameter exists only for interface compatibility. Should either be removed or used for something (e.g., full-text search fallback).

**m4. `CodeChunk` schema missing `function_name`, `class_name` fields** (store.py:70-94)
For code-aware search, users would want to filter by function or class name. The schema only has `path`, `language`, `line_start`, `line_end`. No structural metadata from the code itself.

**m5. `_get_language()` returns lowercase strings but no validation** (indexer.py:486-497)
The method silently returns `"text"` for any unknown extension. There's no way to know which files were indexed as generic text vs. their actual language. Could lead to confusion in search results where `language: "text"` means "unknown".

**m6. `prepare_document()` imports `get_config` inside function body** (indexer.py:203)
This import runs on every call. Since `prepare_document()` is called in a `ThreadPoolExecutor`, the import lock is hit concurrently. Not a bug (Python handles this safely) but wasteful. The import should be at module level or cached.

**m7. CodebaseIndexer meta uses string paths as keys, VaultIndexer uses stems** (indexer.py:599 vs 440)
`CodebaseIndexer._write_meta()` saves `str(p.relative_to(self.root_dir))` as keys. `VaultIndexer._save_meta_from_paths()` saves `doc_id` (which is `path.stem`). Inconsistent keying makes it harder to share metadata logic or compare state across indexer types.

**m8. `VaultStore.__exit__` return type annotation says `bool` but should be `bool | None`** (store.py:146-154)
The `__exit__` method returns `False` (don't suppress exceptions). The type annotation `-> bool` is technically correct but conventionally `-> bool | None` or `-> None` since the return value is only meaningful when `True`.

______________________________________________________________________

## Round 2: Test Coverage

Audited files:

- `src/vaultspec_rag/tests/test_indexer_unit.py`
- `src/vaultspec_rag/tests/test_search_unit.py`
- `src/vaultspec_rag/tests/test_store.py`
- `src/vaultspec_rag/tests/test_store_codebase.py`
- `src/vaultspec_rag/tests/test_query.py`
- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`
- `src/vaultspec_rag/tests/integration/conftest.py`
- `src/vaultspec_rag/tests/conftest.py`
- `conftest.py`

### Test Inventory

| Test File                               | Marker              | Tests | Covers                                                                                |
| --------------------------------------- | ------------------- | ----- | ------------------------------------------------------------------------------------- |
| test_indexer_unit.py                    | unit                | 11    | `_extract_title`, `_extract_feature`, `IndexResult`, `prepare_document`               |
| test_search_unit.py                     | unit+integration    | 19    | `ParsedQuery`, `SearchResult`, `parse_query`, `_rerank`                               |
| test_query.py                           | unit                | 6     | `parse_query` (duplicate of test_search_unit.py)                                      |
| test_store.py                           | unit                | 8     | `_build_filter`, `_stable_id`                                                         |
| test_store_codebase.py                  | integration         | 4     | `ensure_code_table`, `upsert_code_chunks`, `_build_code_filter`, `delete_code_chunks` |
| integration/test_indexer_integration.py | integration+quality | 7     | `VaultIndexer.full_index`, `incremental_index`, `prepare_document`                    |

### CRITICAL Test Gaps

**T-C1. Zero tests for CodebaseIndexer**
No unit tests, no integration tests. `CodebaseIndexer.full_index()`, `_scan_codebase()`, `_chunk_file()`, `_get_language()` are completely untested. This is the primary module being overhauled and has zero test coverage.

**T-C2. Zero tests for TextSplitter**
`TextSplitter.__init__()`, `split_text()`, and `_recursive_split()` have no tests at all. This is the chunking core of the codebase indexer. Edge cases (empty string, text shorter than chunk_size, text with no matching separators, overlap behavior) are untested.

**T-C3. Zero tests for `search_all()` / `search()` combined pipeline**
`VaultSearcher.search_all()` combines vault and codebase results with incompatible score scales (M8 from Round 1). No test verifies the combined pipeline works correctly or that results are properly ranked.

### MAJOR Test Gaps

**T-M1. No test for `tag` filter end-to-end**
`test_search_unit.py:test_tag_filter` (line 61-64) tests that `parse_query("tag:#research")` extracts the tag. But no test verifies the tag filter actually reaches Qdrant and filters results. This maps to M7 — the bug would be caught by an integration test.

**T-M2. No test for `search_codebase()` pipeline**
`VaultSearcher.search_codebase()` has no integration or unit tests. The codebase search path (including lang/path filters, sparse encoding, hybrid search on codebase collection) is untested.

**T-M3. No test for `hybrid_search_codebase()` in VaultStore**
`test_store_codebase.py` tests CRUD operations but not the actual search path. `hybrid_search_codebase()` with dense+sparse fusion has no test coverage.

**T-M4. `test_query.py` is entirely duplicated by `test_search_unit.py`**
Both files test `parse_query()` with the same scenarios. `test_query.py` has 6 tests; `test_search_unit.py:TestParseQuery` has 13 tests (superset). `test_query.py` should be deleted to avoid confusion and maintenance overhead.

**T-M5. No test for `rerank_with_graph()` function**
The graph-aware reranking function (search.py:93-139) is untested. No test verifies that in-link count boost or feature-neighbor boost work correctly. This is a non-trivial scoring algorithm with potential for subtle bugs.

**T-M6. `_fast_index()` conftest helper calls dead `_save_meta()` method**
`conftest.py:65` calls `indexer._save_meta(docs)` which is the unused method identified in m2. This works only because `_save_meta()` reconstructs paths from `docs_dir / doc.path` — if a test doc's relative path doesn't match the actual filesystem path, mtime metadata will silently fail (the `contextlib.suppress(OSError)` swallows the error).

**T-M7. No test for `VaultStore.get_by_id()`**
The `get_by_id()` method (store.py:352-373) has no test coverage. It performs a payload transformation (`doc_id` -> `id`) that could easily break.

### MINOR Test Gaps

**T-m1. `test_returns_doc_for_audit_dir` is semi-tautological** (test_indexer_unit.py:88-96)
The test has `if audit_files:` and `if doc is not None:` guards that mean it passes even when no audit files exist or when `prepare_document` returns None. It asserts nothing in the failure paths. Per CLAUDE.md, tests that can silently pass without testing anything must be deleted or strengthened.

**T-m2. No test for `VaultStore.close()` / context manager protocol**
`__enter__` / `__exit__` / `close()` are untested. While simple, a regression in `close()` could leave Qdrant locks open.

**T-m3. Integration conftest creates duplicate `rag_components` fixture**
Both `src/vaultspec_rag/tests/conftest.py` (line 127-142) and `src/vaultspec_rag/tests/integration/conftest.py` (line 14-29) define `rag_components`. The integration version uses `QDRANT_SUFFIX_UNIT` while the parent uses `QDRANT_SUFFIX_FAST`. This shadowing is intentional but confusing — a test's behavior depends on which conftest pytest discovers first.

**T-m4. No negative test for `_stable_id` collision detection**
`test_store.py:test_stable_id_different_inputs` only tests two specific inputs. No test verifies behavior when two different strings happen to produce the same hash (which would be a serious bug). A property-based test (hypothesis) would be more robust.

**T-m5. `TestRerank.test_rerank_single_result_skipped` uses synthetic SearchResult**
This test creates a `SearchResult` with `score=0.5` and `snippet="Some content about architecture."` — a synthetic fixture. Per CLAUDE.md, tests should use real data. The other two rerank tests correctly use real search results from the store.

______________________________________________________________________

## Round 3: Gap Analysis vs Research & Prior Audit

### Prior Audit Discrepancy

`docs/audit/2026-03-06-indexer-pipeline.md` (passes 18-27) marked the indexer as "SOLID" and "All confirmed correct" with "No new issues found." This audit missed all 9 known issues and the 14 additional issues identified in Round 1. The prior audit's scope was too shallow (focused on `.tolist()` fix verification) and incorrectly gave an all-clear.

### Research Doc Status

`docs/research/2026-03-06-codebase-indexer-tech-stack.md` is NOT YET AVAILABLE (docs-researcher task #1 still in progress). A full gap analysis will be added when it arrives. Partial analysis follows based on existing research docs and known industry best practices.

### Gap Analysis: Current Implementation vs Industry Best Practices

| Area                         | Current State                                                                         | Industry Standard (2025-2026)                                                                                                                                                                                                           | Gap Severity         |
| ---------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| **Code chunking**            | `TextSplitter` — regex-based, character-level splits at `\nclass`, `\ndef` etc.       | **tree-sitter AST chunking** — parse code into AST, split at function/class boundaries, depth-first walk merging siblings to token limit. Used by Cursor, Cody, CocoIndex. cAST paper: +4.2 pts on StarCoder2-7B vs character chunking. | CRITICAL             |
| **Gitignore compliance**     | `git ls-files` (works in git repos) with `rglob("*")` fallback that ignores gitignore | **`pathspec` library** — loads `.gitignore` patterns, handles nested gitignores, works outside git repos. Used by black, ruff, pre-commit.                                                                                              | MAJOR                |
| **Incremental indexing**     | VaultIndexer: mtime-based. CodebaseIndexer: none (full re-embed every time).          | **SHA256 content hash** per file — more reliable than mtime (mtime can change without content change, and vice versa on some filesystems). Cursor uses Merkle tree hashing every 10 min.                                                | MAJOR                |
| **Language support**         | 7 extensions: .py, .rs, .md, .js, .ts, .tsx, .jsx                                     | **100+ languages** via `tree-sitter-languages` — pre-built grammars for all major languages.                                                                                                                                            | MAJOR                |
| **Code metadata**            | None — chunks have only `path`, `language`, `line_start`, `line_end`                  | **Structural metadata**: `function_name`, `class_name`, `module_name`, `docstring`, `signature`. Enables filtering like `class:MyClass lang:python`.                                                                                    | MAJOR                |
| **Binary detection**         | None — relies on `read_text()` exception handling                                     | **Null byte check** in first 8KB, or `python-magic` for MIME type detection.                                                                                                                                                            | MINOR                |
| **File size limits**         | None                                                                                  | **Configurable max (10MB default)**, skip or warn on oversized files.                                                                                                                                                                   | MINOR                |
| **Embedding model for code** | Qwen3-Embedding-0.6B (general-purpose)                                                | **Code-specific models**: voyage-code-3, CodeSage, StarEncoder. Qwen3-Embedding-0.6B is adequate but not optimized for code search.                                                                                                     | LOW (investigate)    |
| **Overlap strategy**         | Character-level tail overlap (broken)                                                 | **AST-aware overlap** — include parent node context (e.g., class signature) in child chunks. Or no overlap when AST boundaries are clean.                                                                                               | MAJOR (with AST fix) |
| **Score normalization**      | None — vault (graph-boosted) and codebase (CrossEncoder logits) scores mixed          | **Score normalization** before fusion — min-max or z-score normalization per source. Or separate result lists with source labels.                                                                                                       | MAJOR                |

### Priority Recommendations

1. **Replace TextSplitter with tree-sitter AST chunking** — This is the single highest-impact change. It fixes C1 (line tracking), C2 (chunk ID collisions), M5 (broken overlap), M6 (JS/TS generic separators), and m4 (missing structural metadata) all at once.

1. **Add `incremental_index()` to CodebaseIndexer** — Use SHA256 content hash instead of mtime for reliability. This fixes C3 and makes codebase indexing practical for large repos.

1. **Replace `rglob("*")` fallback with `pathspec`** — Fixes M2 and works everywhere (not just git repos).

1. **Add score normalization in `search_all()`** — Fixes M8 (incompatible score scales).

1. **Fix `tag` filter passthrough** — Fixes M7 (silent correctness bug). Quick fix: add `"tag"` handling to `_build_filter()` and `search_vault()`.

### Awaiting

- `docs/research/2026-03-06-codebase-indexer-tech-stack.md` from docs-researcher — will contain specific API examples for tree-sitter-languages, pathspec, and content hashing.
- Will extend this gap analysis when research arrives.

______________________________________________________________________

## Round 4: MCP Server, CLI, and Cross-Cutting Issues

Audited files:

- `src/vaultspec_rag/mcp_server.py`
- `src/vaultspec_rag/cli.py`
- `src/vaultspec_rag/embeddings.py` (cross-reference)

### MAJOR Issues

**R4-M1. `reindex_codebase` MCP tool always does full re-index** (mcp_server.py:226-247)
The MCP tool `reindex_codebase()` calls `comp.code_indexer.full_index()` unconditionally. Unlike `reindex_vault()` which has a `clean` flag toggling full vs incremental, the codebase tool has no incremental option. This is a direct consequence of C3 (missing `incremental_index()` on CodebaseIndexer). The MCP tool docstring even says "always a full re-index" — acknowledging the limitation.

**R4-M2. CLI `index --type=code` always does full re-index** (cli.py:204-211)
Same issue in the CLI: `c_indexer.full_index()` is called unconditionally. When `--clean` is not set, vault uses `incremental_index()` (line 193) but codebase still does full. Asymmetric behavior — users would expect `--type=all` to do incremental for both.

**R4-M3. CLI `search --type` doesn't support `all`** (cli.py:246-249)
The `search` command accepts `Literal["vault", "code"]` but not `"all"`. The `search_all()` method exists and the MCP server exposes it, but the CLI doesn't. Users must run two separate searches to cover both.

**R4-M4. CLI `search` creates new EmbeddingModel + VaultStore on every invocation** (cli.py:263-265)
Each `search` call creates a new `VaultStore(target)` and `EmbeddingModel()`. The EmbeddingModel constructor loads ~1.5GB of model weights onto GPU. For a single search this is acceptable, but if a user runs multiple searches in sequence (scripting, interactive use), each invocation re-loads the model. No caching or warm-start mechanism.

**R4-M5. `get_code_file` MCP tool has path traversal protection but returns raw errors** (mcp_server.py:179-194)
The `is_relative_to()` check prevents reading files outside the workspace — good. But the error messages include full filesystem paths and exception details (`f"Error reading file '{path}': {e}"`), which could leak internal path structure to untrusted MCP clients.

**R4-M6. MCP `search_vault` passes SearchResult to Pydantic via `from_attributes=True`** (mcp_server.py:122)
`SearchResultItem.model_validate(r, from_attributes=True)` expects `r` to be an object with attributes, not a dataclass with different field names. `SearchResult.snippet` maps correctly, but if the dataclass fields ever diverge from the Pydantic model, this will silently produce empty/wrong values. There's no explicit field mapping or validation test.

### MINOR Issues

**R4-m1. CLI skips workspace resolution for `test` and `server` commands** (cli.py:113-114)
`if ctx.invoked_subcommand in ("test", "server"): return` — this skips the workspace resolution. But other commands that don't need workspace (like a hypothetical `version` or `help`) would still try to resolve. The logic should be inverted: only resolve workspace for commands that need it.

**R4-m2. CLI `handle_test` uses subprocess instead of pytest API** (cli.py:429-434)
`subprocess.call([sys.executable, "-m", "pytest", ...])` spawns a new process. This works but loses the ability to set pytest configuration programmatically or capture structured results. Not necessarily wrong, but worth noting.

**R4-m3. MCP server module-level import of `CodebaseIndexer`, `VaultIndexer`** (mcp_server.py:18-19)
These imports happen at module load time, before any tool is called. If the module is imported in a non-RAG context (e.g., for inspection), it will succeed because the imports are just type references. But `get_comp()` then creates instances, which triggers GPU initialization. This is fine architecturally but means importing `mcp_server` has no cost while calling any tool has a heavy cold-start.

**R4-m4. `EmbeddingModel` has no way to specify code vs document prompt** (embeddings.py:213-239)
`encode_documents()` uses no prompt prefix. `encode_query()` uses `prompt_name="query"`. For code chunks, the optimal embedding might benefit from a code-specific prompt (e.g., "Represent this code for retrieval:"). Currently all document types — vault markdown and source code — get the same treatment.

**R4-m5. `CLIState` sets `VAULTSPEC_ROOT` env var as side effect** (cli.py:58)
The constructor mutates the process environment. This means importing and creating CLIState changes global state. If multiple tests or commands create CLIState with different targets, they'll overwrite each other's env vars. Not a problem for CLI (single-shot process) but could cause issues in tests.

**R4-m6. `handle_status` imports `torch` unconditionally** (cli.py:299)
The `status` command imports `torch` even if the user just wants to see the storage path. If torch isn't installed, the status command fails entirely instead of showing partial info.

______________________________________________________________________

## Round 5: Public API, Workspace, and Cross-Module Analysis

Audited files:

- `src/vaultspec_rag/__init__.py`
- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/workspace.py`
- `src/vaultspec_rag/tests/test_cli.py`
- `src/vaultspec_rag/tests/test_mcp_server.py`

### MAJOR Issues

**R5-M1. `__init__.py` does not export `CodebaseIndexer`** (**init**.py:9-36)
`__all__` exports `VaultIndexer`, `VaultSearcher`, `VaultStore`, etc. but `CodebaseIndexer` is absent. Users must import it directly from `vaultspec_rag.indexer`. This is inconsistent — the MCP server and CLI both use `CodebaseIndexer`, but the public API pretends it doesn't exist.

**R5-M2. `api.py` has no codebase API functions** (api.py:1-128)
The public API facade (`index()`, `list_documents()`, `get_related()`) only operates on vault documents. There's no `index_codebase()`, `search_codebase()`, or `list_code_chunks()`. The API module is vault-only, while the CLI and MCP server support both vault and codebase. Users of the programmatic API have to wire up CodebaseIndexer manually.

**R5-M3. `api._Engine` singleton can't switch roots** (api.py:43-48)
`get_engine(root_dir)` creates a new engine if `root_dir` changes but doesn't close the old one. The old `VaultStore` stays open with its Qdrant client, potentially holding file locks on the old `.qdrant/` directory. Repeated calls with different roots will leak Qdrant connections.

**R5-M4. `list_documents()` does N+1 queries** (api.py:85-97)
For each document ID returned by `get_all_ids()`, it calls `get_by_id()` individually. Each `get_by_id()` does a Qdrant `retrieve()` call. For 213 documents, that's 214 Qdrant calls (1 scroll + 213 retrieves). Should use a batch retrieve or scroll with full payloads.

### MINOR Issues

**R5-m1. `test_cli.py` has no tests for `index`, `search`, or `status` with real workspace** (test_cli.py)
CLI tests only check help output, arg parsing, and workspace-not-found errors. No test actually runs `index`, `search`, or `status` against a real workspace with GPU. The core CLI functionality is untested beyond arg parsing.

**R5-m2. `test_mcp_server.py` only tests registration and Pydantic models** (test_mcp_server.py)
MCP tests verify that tools/prompts are registered and that Pydantic models validate. No test actually calls any MCP tool with real data. All tool functions (`search_vault`, `reindex_vault`, etc.) are untested.

**R5-m3. `workspace.py` checks for `.gt/` container directory** (workspace.py:109-118)
The `discover_git()` function checks for `.gt/` as a "container" directory. This appears to be a custom convention not part of standard git. If any directory happens to have a `.gt/` folder, it will be misdetected as a bare repo container, returning `is_bare=True`. Potential for false positives.

**R5-m4. `get_related()` returns empty dict on graph build failure** (api.py:115-117)
When `VaultGraph(root_dir)` raises an exception, `get_related()` returns `{"doc_id": doc_id, "outgoing": [], "incoming": []}` — an empty result that looks like the doc has no links. The caller can't distinguish "no links" from "graph failed to build." Should either raise or include an error field.

______________________________________________________________________

## Round 6: pyproject.toml, Dependencies, and Configuration Audit

Audited files:

- `pyproject.toml`
- `src/vaultspec_rag/logging_config.py`

### MAJOR Issues

**R6-M1. `vaultspec` dependency uses absolute local path** (pyproject.toml:20)
`"vaultspec @ file:///C:/projects/worktrees/main"` — this hard-codes a Windows-specific absolute path. The package cannot be installed by anyone else, in CI, or on any machine where `C:/projects/worktrees/main` doesn't exist. Should use a relative path or proper package registry.

**R6-M2. Duplicate dev dependencies in both `[project.optional-dependencies]` and `[dependency-groups]`** (pyproject.toml:31-57)
Lines 32-43 (`[project.optional-dependencies] dev`) and lines 46-57 (`[dependency-groups] dev`) contain the same packages. This is confusing — uv reads `[dependency-groups]` (PEP 735) while `[project.optional-dependencies]` is the older PEP 621 surface. If one is updated and the other forgotten, they'll diverge silently.

**R6-M3. Marker descriptions in `[tool.pytest.ini_options]` are misleading** (pyproject.toml:84-85)

- `unit` says "fast tests with no external dependencies" — but unit tests import `qdrant-client` and `vaultspec` (external deps). Should say "no GPU, no network, no disk I/O beyond fixtures."
- `integration` says "requires CLI tools and network" — but integration tests require CUDA GPU + Qdrant + real model inference, not "CLI tools and network."

### MINOR Issues

**R6-m1. No `flash-attn` in dependencies** (pyproject.toml:13-25)
`embeddings.py` tries to import `flash_attn` and falls back gracefully. But `flash-attn` is not listed anywhere in pyproject.toml (not even as optional). Users won't know it's available or how to install it. Should be in `[project.optional-dependencies]` as an optional extra.

**R6-m2. `qdrant-client>=1.12.0` might be too low** (pyproject.toml:17)
The code uses `query_points()` with `FusionQuery(RRF)` which was introduced in qdrant-client 1.17+. The minimum version should be `>=1.17.0` to match actual API usage.

**R6-m3. `configure_logging()` clears ALL root logger handlers** (logging_config.py:83-84)
`root.handlers[:]` is cleared on every configure call. If any other library has attached handlers to the root logger (e.g., pytest's own logging), they'll be removed. This can suppress test log output unexpectedly.

**R6-m4. `logging_config._configured` flag prevents reconfiguration** (logging_config.py:60-61)
Once `configure_logging()` runs, it can't be called again with different settings unless `reset_logging()` is called first. The CLI calls `configure_logging(debug=debug, level=...)` once in the callback. If a subcommand needs different log settings, it can't override.

**R6-m5. No `py.typed` marker file** (src/vaultspec_rag/)
PEP 561 requires a `py.typed` marker file for type-checker support. The package uses strict typing (per CLAUDE.md) but doesn't include the marker, so external consumers won't get type checking benefits.

______________________________________________________________________

## Round 7: Integration Test Quality and Remaining Test Files

Audited files:

- `src/vaultspec_rag/tests/integration/test_search_integration.py`
- `src/vaultspec_rag/tests/integration/test_store_integration.py`
- `src/vaultspec_rag/tests/integration/test_quality.py`
- `src/vaultspec_rag/tests/integration/test_robustness.py`
- `src/vaultspec_rag/tests/integration/test_performance.py`
- `src/vaultspec_rag/tests/integration/test_api_integration.py`

### Assessment: Integration Tests Are Strong for Vault Search

The existing integration test suite is well-designed for vault document search:

- **Quality tests** (test_quality.py): 15 tests covering known-answer precision, filter correctness, ranking quality, negative tests. Good grounding in actual test corpus content.
- **Robustness tests** (test_robustness.py): 7 tests for edge cases (no frontmatter, Unicode, YAML separators, graph orphans).
- **Performance tests** (test_performance.py): 10 tests for latency bounds, disk footprint, graph caching.
- **Search integration** (test_search_integration.py): 11 tests for end-to-end search, edge cases, SQL injection resilience.
- **API integration** (test_api_integration.py): 10 tests for the public API facade.
- **Store integration** (test_store_integration.py): 5 tests for store CRUD + hybrid search.

### Remaining Gaps (CodebaseIndexer-specific)

**R7-M1. Zero integration tests for codebase search** (all integration test files)
All integration tests exercise `VaultSearcher.search()` and `VaultSearcher.search_vault()`. No test calls `search_codebase()`, `search_all()`, or `hybrid_search_codebase()`. The entire codebase search pipeline is untested at the integration level.

**R7-M2. Zero quality tests for codebase results** (test_quality.py)
Quality tests assert precision, filter accuracy, and ranking for vault docs. No equivalent exists for code chunks. There's no known-answer test like "searching for 'def encode_query' should return embeddings.py."

**R7-M3. Zero performance tests for codebase indexing** (test_performance.py)
Performance tests measure vault indexing latency, query latency, and disk footprint. No test measures codebase indexing throughput, codebase search latency, or codebase storage footprint.

### MINOR Issues

**R7-m1. `test_search_result_has_snippet` is conditionally tautological** (test_search_integration.py:85-86)
The `if results:` guard means the test passes silently when search returns empty results. Should use `assert results` to fail explicitly.

**R7-m2. Performance test FTS comment is stale** (test_performance.py:26-28)
Comment says "fts_dirty starts True on VaultStore init, so the first search rebuilds the FTS index." This refers to the old LanceDB/Tantivy FTS implementation. Qdrant doesn't have an FTS rebuild concept. The warmup is still valid (GPU model warmup) but the comment is misleading.

**R7-m3. `test_api_integration.py` tests don't actually test the API facade** (test_api_integration.py:22-54)
Tests labeled "rag.api.search" actually create a `VaultSearcher` directly from `rag_components`, bypassing the `api.py` facade entirely. Only `test_index_incremental`, `test_index_full`, `test_list_documents*`, and `test_get_related` actually call `api.py` functions. The test class name and docstrings are misleading.

**R7-m4. `test_nonsense_query` uses absolute threshold that may break with reranker** (test_quality.py:349-370)
The test asserts `max_score < 0.10` for nonsense queries. But when the CrossEncoder reranker is enabled, it produces logit-scale scores (can be negative or >>1). The threshold only works for RRF fusion scores. If the default reranker config changes, this test will break.

______________________________________________________________________

## Round 8: ADR Consistency and Documentation Cross-Reference

Audited files:

- `docs/adr/2026-03-06-gpu-only-rag-stack.md`
- `docs/adr/2026-03-06-rag-stack-migration.md`

### MINOR Issues

**R8-m1. ADR says `qdrant-client>=1.17` but pyproject.toml says `>=1.12.0`** (adr gpu-only-rag-stack.md:86, pyproject.toml:17)
The accepted ADR explicitly states: "Add: ... `qdrant-client>=1.17`". But `pyproject.toml` still has `qdrant-client>=1.12.0`. This means the ADR decision was not fully implemented. (Also flagged as R6-m2.)

**R8-m2. ADR says `flash-attn>=2.5` should be optional dependency** (adr gpu-only-rag-stack.md:90)
The ADR states: "Optional: `flash-attn>=2.5` (for flash_attention_2 acceleration)." But it's not listed in `pyproject.toml` at all — not even in `[project.optional-dependencies]`. (Also flagged as R6-m1.)

**R8-m3. Superseded ADR still says `status: accepted`** (adr rag-stack-migration.md:4)
The frontmatter says `status: accepted` but also `superseded-by: 2026-03-06-gpu-only-rag-stack`. The status should be `superseded` for consistency. The superseding ADR correctly says "supersedes" in its metadata.

**R8-m4. ADR mentions `CrossEncoder` reranker but doesn't include it in the decision** (adr gpu-only-rag-stack.md)
The "Public Interface" section lists `CodebaseIndexer` but never mentions the CrossEncoder reranker (`cross-encoder/ms-marco-MiniLM-L6-v2`) which was added to the implementation. The reranker is present in `config.py` defaults and `search.py` but absent from either ADR. It should have its own ADR or be documented in the existing one.

**R8-m5. ADR "Consequences" mentions CI needing GPU runners or mocking** (adr gpu-only-rag-stack.md:131)
Quote: "CI/CD must have GPU runners or mock the embedding layer for tests." But CLAUDE.md explicitly forbids mocking: "No mocks, patches, fakes, stubs, monkeypatches." The ADR consequence contradicts the project's testing mandate. CI must have GPU runners, period.

______________________________________________________________________

## Round 9: New Code Audit — ASTChunker, pathspec scan, incremental_index

Audited files (new/rewritten code):

- `src/vaultspec_rag/indexer.py` — ASTChunker (242-378), `_scan_codebase()` (729-777), `incremental_index()` (932-1012), `_get_chunk_ids_for_files()` (1014-1022), `_chunk_with_ast()` (801-836)
- `src/vaultspec_rag/store.py` — CodeChunk dataclass (70-94)

### Status of Previously-Reported Critical Issues

- **C1 (line tracking):** FIXED. ASTChunker uses `node.start_point[0]` / `node.end_point[0]` from tree-sitter, which are exact. No more `content.find(text)`.
- **C2 (chunk ID collision):** FIXED. New format `{rel_path}:{line_start}-{line_end}:{sha256[:12]}` includes a 12-char content hash suffix. Collision requires identical content at identical line ranges.
- **C3 (missing incremental_index):** FIXED. `CodebaseIndexer.incremental_index()` implemented at lines 932-1012 using SHA256 content hashing.
- **M1 (7 extensions):** FIXED. `LANGUAGE_MAP` now has 23 extensions covering Python, Rust, JS/TS/JSX/TSX, Go, Java, C/C++/H/HPP/CC, C#, Ruby, Shell/Bash, YAML, TOML, JSON, HTML, CSS, Kotlin.
- **M2 (gitignore):** FIXED. `_scan_codebase()` uses `pathspec.GitIgnoreSpec` instead of `git ls-files`.
- **M3 (binary detection):** FIXED. `_is_binary()` checks first 8KB for null bytes.
- **M4 (file size):** FIXED. `_MAX_FILE_SIZE = 10MB` guard on line 230.

### CRITICAL Issues (New)

**R9-C1. `_get_chunk_ids_for_files()` is O(n\*m) — fetches ALL IDs and filters in Python** (indexer.py:1014-1022)

```python
def _get_chunk_ids_for_files(self, rel_paths: set[str]) -> list[str]:
    all_ids = self.store.get_all_code_ids()
    return [
        cid for cid in all_ids
        if any(cid.startswith(f"{rp}:") for rp in rel_paths)
    ]
```

This method calls `self.store.get_all_code_ids()` which must scroll the entire Qdrant `codebase_docs` collection to retrieve every chunk ID. Then it does an O(n\*m) list comprehension where n = total chunk count and m = number of files to remove. For a codebase with 50K chunks and 100 modified files, this is 5 million `str.startswith()` calls per incremental index.

**CORRECTION:** `get_all_code_ids()` (store.py:326) and `delete_code_chunks()` (store.py:303) both exist on VaultStore. The earlier grep hit a stale read. incremental_index() will NOT crash. The O(n\*m) performance concern remains valid — downgraded to MAJOR.

**Fix:** Add a `get_code_ids_by_path_prefix()` method to VaultStore that uses Qdrant's scroll with a payload filter (`path` field match). This pushes the filtering to Qdrant and avoids loading all IDs into Python. Alternatively, use a `Filter` with `FieldCondition(key="path", match=MatchAny(any=[...]))`.

### MAJOR Issues (New)

**R9-M1. `CodeChunk` dataclass missing `node_type` field** (store.py:70-94) **-- FIXED**
ASTChunker now produces 6-tuples `(text, line_start, line_end, node_type, function_name, class_name)`. CodeChunk updated with `node_type: str | None`, `function_name: str | None`, `class_name: str | None`. `_chunk_with_ast()` passes all fields. New constants `_CLASS_LIKE_NODES` and `_FUNCTION_LIKE_NODES` + `_extract_name()` method for AST name extraction. `class_name` propagates downward via `parent_class_name`/`child_class_name` parameters.

**R9-M2. `_collect_chunks` force-split of large leaf nodes produces wrong line numbers** (indexer.py:303-309)
When a leaf node exceeds `chunk_size`, the code force-splits by character offset and recomputes line numbers:

```python
abs_byte = node.start_byte + i
ls = source[:abs_byte].count("\n") + 1
le = ls + segment.count("\n")
```

`source[:abs_byte].count("\n")` is O(n) per segment — for a 100KB leaf node split into 67 segments of 1500 chars, this does 67 scans of up to 100KB each = ~6.7MB of string scanning. Should maintain a running line counter.

More critically: if the source file uses `\r\n` line endings (Windows), `.count("\n")` is correct but `source[:abs_byte]` slicing by byte offset is wrong — Python strings are character-indexed while `node.start_byte` is a byte offset into the UTF-8 encoded source. For ASCII this is identical, but for files with multi-byte UTF-8 characters (Unicode identifiers, string literals with CJK), the byte offset and character offset diverge, producing wrong line numbers and extracting the wrong text slice.

**R9-M3. `buffer_start` type unsafety — `None` used where `int` expected** (indexer.py:314, 327, 336, 351)
`buffer_start` is declared as `int | None = None` (line 314). When the buffer is flushed at lines 327, 336, and 351, `buffer_start` is used in the tuple `(merged, buffer_start, buffer_end, None)`. The `# type: ignore[arg-type]` suppresses the type error. But the return type declares `list[tuple[str, int, int, str | None]]` — the `int` position is not optional. If `buffer_start` is somehow still `None` when the tuple is emitted (e.g., a code path where `buffer_parts` is non-empty but `buffer_start` was never set), downstream consumers will get `None` where they expect `int`, causing failures in Qdrant payload construction or chunk ID formatting.

Current code does set `buffer_start` before appending to `buffer_parts` in the `else` branch (line 344), and the other branch (line 338) also sets it. So in practice `buffer_start` is always an `int` when `buffer_parts` is non-empty. But the type suppression hides this invariant from the type checker, making future refactors risky.

**R9-M4. `_scan_codebase` pathspec prefix logic is incorrect for subdirectory `.gitignore` negation patterns** (indexer.py:748-757)
For `.gitignore` files in subdirectories, the code prepends the relative directory:

```python
patterns.append(f"{str(rel_dir).replace(chr(92), '/')}/{stripped}")
```

This works for simple patterns like `*.log` becoming `subdir/*.log`. But gitignore negation patterns (`!important.log`) become `subdir/!important.log` — the `!` is no longer at the start of the pattern, so pathspec won't interpret it as a negation. The file will remain excluded.

Similarly, anchored patterns (starting with `/`) like `/build` in a subdirectory gitignore should become `subdir/build`, but the current code produces `subdir//build` (double slash). While pathspec may normalize this, the behavior is untested and gitignore semantics for subdirectory patterns are subtle.

**R9-M5. `incremental_index()` reads all files twice — once for hashing, once for chunking** (indexer.py:952-956, 974)
Lines 952-956 hash every current file via `path.read_bytes()`. Then lines 972-974 chunk modified files via `self._chunk_file()` which calls `path.read_text()` — a second read of the same file. For large codebases with many unchanged files this is acceptable (hash is cheap, only modified files are re-read). But for modified files, they're read twice unnecessarily. Could cache the content from the hashing pass.

**R9-M6. `incremental_index()` has no error handling for `read_bytes()` during hashing** (indexer.py:953-956)

```python
for rel, path in current_files.items():
    current_hashes[rel] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
```

If `read_bytes()` raises (permission denied, file deleted between scan and hash, symlink to missing target), the entire `incremental_index()` crashes. Unlike `_chunk_file()` which catches exceptions gracefully (line 787-789), the hashing loop has no error handling. A single unreadable file kills the entire incremental index.

### MINOR Issues (New)

**R9-m1. `_merge_small` preserves first non-None metadata on merge** (indexer.py:424-426)

```python
prev[3] or chunk[3],    # node_type: keep first non-None
prev[4] or chunk[4],    # function_name: keep first non-None
prev[5] or chunk[5],    # class_name: keep first non-None
```

When merging two small chunks, the merged chunk gets the first non-None value for each metadata field. If chunk A is `function_definition` with `function_name="foo"` and chunk B is `class_definition` with `class_name="Bar"`, the merged result is labeled `function_definition` with `function_name="foo"` and `class_name=None` (since chunk A had no class_name). This is misleading for `node_type` and loses the class_name from chunk B. Merged multi-node chunks should get `None` for `node_type`.

**R9-m2. `ASTChunker` is instantiated fresh on every file** (indexer.py:809)
`_chunk_with_ast()` creates `ASTChunker()` on each call. The chunker has no state beyond `chunk_size`, so this is wasteful (though cheap). Should be a class attribute or created once in `__init__`.

**R9-m3. `_chunk_with_ast()` discards `node_type` with underscore prefix** (indexer.py:821) **-- FIXED**
Now unpacks all 6 fields: `for text, line_start, line_end, node_type, function_name, class_name in ast_chunks:` and passes them to CodeChunk.

**R9-m4. `_scan_codebase` hardcoded exclusions overlap with typical `.gitignore`** (indexer.py:734-741)
The hardcoded patterns (`.venv/`, `.git/`, `node_modules/`, `__pycache__/`, `.qdrant/`) are always prepended. Most projects already have these in `.gitignore`. The duplication is harmless (pathspec handles duplicates) but adds noise. More importantly, `.qdrant/` is a project-specific convention — it should come from config, not be hardcoded.

**R9-m5. `_collect_chunks` uses `"\n".join(buffer_parts)` which changes whitespace** (indexer.py:326, 335, 350)
When merging sibling nodes into a buffer, the code joins them with `"\n"`. But the original source between siblings may have multiple newlines, blank lines, or comments. The merged chunk loses the original inter-node whitespace. For display/snippet purposes this is acceptable, but for round-trip fidelity (e.g., applying patches based on chunk content), the chunk text won't match the source file.

**R9-m6. ~~`delete_code_chunks()` method does not exist on `VaultStore`~~** **-- RETRACTED**
Both `delete_code_chunks()` (store.py:303) and `get_all_code_ids()` (store.py:326) exist. Earlier grep hit a stale read. See R9-C1 correction.

______________________________________________________________________

## Round 10: Post-Fix Verification and Metadata Propagation Audit

Audited files (current versions):

- `src/vaultspec_rag/indexer.py` — ASTChunker (271-450), `_scan_codebase()` (801-851), `incremental_index()` (1014-1097), `_collect_chunks()` (321-421), `_extract_name()` (313-319)
- `src/vaultspec_rag/store.py` — `upsert_code_chunks()` (238-283), `_build_code_filter()` (566-586), `get_all_code_ids()` (326-329), `delete_code_chunks()` (303-319)

### Fix Verification

**R9-M4 (subdirectory .gitignore negation): VERIFIED FIXED** (indexer.py:828-832)
Negation patterns are now handled correctly:

```python
if stripped.startswith("!"):
    patterns.append(f"!{prefix}/{stripped[1:]}")
else:
    patterns.append(f"{prefix}/{stripped}")
```

The `!` is kept at pattern start and the inner pattern gets the prefix. However, anchored patterns starting with `/` (e.g., `/build` in a subdirectory) are not handled — they become `subdir//build` (double slash from prefix + leading slash). See R10-m3.

**R9-M6 (read_bytes error handling): VERIFIED FIXED** (indexer.py:1036-1041)

```python
try:
    current_hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
except OSError:
    logger.warning("Cannot hash file, skipping: %s", rel)
```

Files that fail hashing are now skipped with a warning. However, this introduces a NEW bug — see R10-M1.

**R9-M1 (CodeChunk node_type): VERIFIED FIXED**
`CodeChunk` has `node_type`, `function_name`, `class_name` fields. `upsert_code_chunks()` stores them in Qdrant payload (store.py:272-274). `_build_code_filter()` supports filtering by all three (store.py:577).

**R9-m3 (\_chunk_with_ast discards node_type): VERIFIED FIXED**
All 6-tuple fields now unpacked and passed to CodeChunk (indexer.py:873).

**R9-M2 (byte vs char offset in force-split): NOT YET FIXED** (indexer.py:359-364)
Still uses `source[:abs_byte]` with byte offset as character index.

**R9-m1 (\_merge_small first-non-None logic): NOT YET FIXED** (indexer.py:444-446)
Still uses `prev[3] or chunk[3]` for node_type, function_name, class_name.

### MAJOR Issues (New)

**R10-M1. `incremental_index()` metadata dict KeyError for files that failed hashing** (indexer.py:1084)

```python
meta = {rel: current_hashes[rel] for rel in current_files}
```

After the R9-M6 fix, files that fail `read_bytes()` are skipped in `current_hashes` (line 1040-1041) but remain in `current_files` (populated from `_scan_codebase()`). The metadata dict comprehension at line 1084 will raise `KeyError` for any such file. The entire `incremental_index()` crashes after completing all the expensive embedding work. Fix: use `current_hashes` as the iteration source, or filter `current_files` to only include successfully hashed files.

**R10-M2. `incremental_index()` treats unhashed files as new on every run** (indexer.py:1044-1051)
Files that fail hashing (R9-M6 fix) are absent from `current_hashes` but present in `curr_files` (line 1045). On the next incremental run, they'll appear in `new_files = curr_files - prev_files` (line 1046) since they were never saved to metadata. The indexer will attempt to chunk and embed them every run, fail at hashing again, and waste time. Should exclude unhashed files from `curr_files` entirely.

**R10-M3. `_extract_name()` byte-offset-as-character-index bug** (indexer.py:319)

```python
return source[name_node.start_byte : name_node.end_byte]
```

Same issue as R9-M2: `start_byte`/`end_byte` are UTF-8 byte offsets, but Python string slicing is by character index. For identifiers with multi-byte UTF-8 characters (e.g., Unicode variable names in Python 3, CJK), this returns the wrong substring. Low probability in practice since most identifiers are ASCII, but technically incorrect. Fix: use `node.text.decode("utf-8")` or compute character offsets from byte offsets.

**R10-M4. `decorated_definition` in `_FUNCTION_LIKE_NODES` is ambiguous** (indexer.py:258)
In Python's tree-sitter grammar, `decorated_definition` wraps both decorated functions AND decorated classes:

```python
@dataclass
class Foo: ...   # node_type = "decorated_definition"

@app.route("/")
def index(): ... # node_type = "decorated_definition"
```

Both produce `decorated_definition` nodes. Currently it's in `_FUNCTION_LIKE_NODES` only, so `@dataclass class Foo` gets `function_name="Foo"` and `class_name=None` — wrong. The code should check the child node type: if the child is `class_definition`, treat it as a class; if `function_definition`, treat it as a function.

### MINOR Issues (New)

**R10-m1. `_FUNCTION_LIKE_NODES` missing `arrow_function` and `method_definition`** (indexer.py:251-259)
JavaScript/TypeScript heavily use arrow functions (`const handler = () => { ... }`) which have node type `arrow_function`. Also `method_definition` inside class bodies (e.g., `class Foo { bar() {} }`). These functions won't get `function_name` extracted. Similarly, Java is missing `constructor_declaration`.

**R10-m2. `_CLASS_LIKE_NODES` missing some node types** (indexer.py:233-248)

- Kotlin: missing `interface_declaration` (Kotlin has interfaces)
- Java: missing `enum_declaration`
- Rust: missing `union_item`
- Go: `type_declaration` is included but Go interfaces are `type_spec` inside `type_declaration` — the name field may be on the inner `type_spec`, not the `type_declaration` itself

**R10-m3. Anchored patterns in subdirectory .gitignore still produce double slash** (indexer.py:832)
A pattern like `/build` in `subdir/.gitignore` becomes `subdir//build`. While pathspec may normalize this, the behavior is untested. Fix: strip the leading `/` before prefixing.

**R10-m4. `_containers` set created on every `_collect_chunks` call** (indexer.py:342-345)

```python
_containers = {"module", "program", "translation_unit", "source_file", "compilation_unit"}
```

This frozenset is created inside `_collect_chunks()` which is called recursively for every AST node. Should be a module-level constant.

**R10-m5. `_collect_chunks` buffer flush does not carry child function metadata** (indexer.py:385-388, 398-401, 417-420)
All buffer flush entries have `function_name=None`. If a small function fits entirely within a buffer merge, its `function_name` is lost. Only direct emission (line 353) preserves function_name. This is by design (merged siblings don't have a single function identity) but means small functions at the top level lose their metadata when merged with imports or other small nodes.

**R10-m6. `full_index()` hashes files after indexing — hash failure doesn't prevent indexing** (indexer.py:994-1000)
`full_index()` hashes files for metadata AFTER chunking and embedding. If a file can be read as text (`_chunk_file()`) but fails `read_bytes()` for hashing, it's indexed but not tracked in metadata. On the next incremental run, it appears as "new" and gets re-indexed. Inconsistent with `incremental_index()` which hashes first.

______________________________________________________________________

## Round 11: Task #13 Fix Verification and Test Quality Audit

Audited files (current versions):

- `src/vaultspec_rag/indexer.py` — force-split fix (359-366), \_merge_small fix (450-463), incremental_index (1038-1113)
- `src/vaultspec_rag/tests/test_indexer_unit.py` — 833 lines, 20+ test classes
- `src/vaultspec_rag/cli.py` — handle_index (125-211)

### Task #13 Fix Verification

**R9-M2 (byte vs char offset in force-split): VERIFIED FIXED** (indexer.py:359-366)
Force-split now uses `node.start_point[0] + 1` for the base line number and `text[:i].count("\n")` for offset — both operate on the Python str, not byte offsets. No more `source[:abs_byte]`.

**R9-m1 (\_merge_small cross-type logic): VERIFIED FIXED** (indexer.py:450-463)
`_merge_small` now checks if both chunks have non-None node_type and they differ — if so, merged node_type is None. The `None or X` case still preserves X (correct). `function_name` and `class_name` still use `or` logic (first non-None wins) — see R11-m1.

**R9-M4 (negation patterns): Previously verified FIXED in Round 10.**

**R9-M6 (read_bytes error handling): Previously verified FIXED in Round 10.** However, R10-M1/R10-M2 are partially addressed — line 1061 now uses `set(current_hashes.keys())` so unhashed files don't enter change detection. But line 1100 still has the bug (see below).

### MAJOR Issues (New/Updated)

**R10-M1 (UPDATED). `incremental_index()` metadata dict still KeyErrors for unhashed files** (indexer.py:1100)
Line 1061 was fixed (`curr_files = set(current_hashes.keys())`), confirmed by the test at test_indexer_unit.py:750. But line 1100 was NOT fixed:

```python
meta = {rel: current_hashes[rel] for rel in current_files}
```

This iterates over `current_files` (all scanned files including those that failed hashing) but looks up in `current_hashes` (only successfully hashed files). If any file fails `read_bytes()`, this line will raise `KeyError` after all embedding work is done. Fix: change to `meta = dict(current_hashes)` or `{rel: h for rel, h in current_hashes.items()}`.

**R11-M1. `_extract_name()` and `_collect_chunks` text extraction still use byte offsets as char indices** (indexer.py:319, 330)
While the force-split path (R9-M2) is fixed, two other critical paths still use `source[node.start_byte : node.end_byte]`:

- Line 319: `source[name_node.start_byte : name_node.end_byte]` in `_extract_name()`
- Line 330: `source[node.start_byte : node.end_byte]` in `_collect_chunks()`
- Line 377: `source[child.start_byte : child.end_byte]` for child text extraction

These are the MAIN text extraction paths — every node's text is extracted this way. For files with multi-byte UTF-8 characters, the extracted text will be wrong for every chunk, not just force-split leaves. The fix: use `node.text.decode("utf-8")` (tree-sitter provides `.text` as bytes) or convert byte offsets to character offsets using the encoded source.

**R11-M2. CLI `handle_index` still uses `full_index()` for code, not `incremental_index()`** (cli.py:205)
`c_indexer.full_index()` is called unconditionally. This was flagged as R4-M2 in Round 4 and remains unfixed. When `--clean` is not set, vault uses `incremental_index()` (line 193) but codebase always does a full re-embed. Fix: use `c_indexer.incremental_index()` when `--clean` is not set.

### Test Quality Assessment

**Positive findings:**

- test_indexer_unit.py now has 20+ test classes with 60+ tests covering ASTChunker, metadata extraction, chunk IDs, language map, binary detection, file size limits, gitignore negation, hashing errors, merge logic, force-split line numbers, and CodeChunk metadata fields
- Tests use real tree-sitter parsing (not mocked) -- compliant with CLAUDE.md
- Regression tests for R9-M2 (non-ASCII force-split), R9-M4 (negation patterns), R9-M6 (hashing errors), R9-m1 (cross-type merge) are all present
- No unittest imports, no mocks, no skips -- clean

**Test issues:**

**R11-m2. `test_returns_doc_for_audit_dir` is still conditionally tautological** (test_indexer_unit.py:99-107)
Previously flagged as T-m1 in Round 2. Still has `if audit_files:` and `if doc is not None:` guards. Test passes silently when no audit files exist or when prepare_document returns None. Per CLAUDE.md, tests that always pass regardless must be strengthened.

**R11-m3. `test_incremental_index_hashing_uses_current_hashes_keys` uses source inspection** (test_indexer_unit.py:740-750)

```python
source = inspect.getsource(CodebaseIndexer.incremental_index)
assert "set(current_hashes.keys())" in source
```

This is a meta-test that inspects source code strings rather than exercising behavior. It's brittle: renaming the variable or reformatting the line breaks the test without any behavioral regression. Should be a behavioral test that verifies unhashed files are excluded from change detection by running the actual method with a controlled filesystem.

**R11-m4. `test_invalid_grammar_falls_back` has a conditional path** (test_indexer_unit.py:384-387)

```python
if not chunks:
    chunks = indexer._chunk_with_splitter(content, "data.py", "python")
```

The test doesn't assert which path was taken. If `_chunk_with_ast` happens to succeed (grammar name might be valid in a future tree-sitter version), the test passes without testing the fallback path. Should assert that `_chunk_with_ast` with invalid grammar returns empty.

### MINOR Issues (New)

**R11-m1. `_merge_small` function_name `or` logic merges names from different functions** (indexer.py:461)
When two chunks from different functions are merged, `prev[4] or chunk[4]` keeps the first function_name. E.g., merging a chunk from `foo()` with one from `bar()` labels the merged chunk as `function_name="foo"`. The class_name `or` logic (line 462) is less problematic since class_name propagates from parent scope and is usually the same for siblings.

______________________________________________________________________

## Round 12: Task #19 Fix Verification and Remaining Byte-Offset Audit

Audited files (current versions):

- `src/vaultspec_rag/indexer.py` — `_extract_name()` (313-327), `_find_decorated_inner()` (329-340), `_collect_chunks()` (342-475), `incremental_index()` (1085-1162)

### Task #19 Fix Verification

**R10-M1 (metadata KeyError for unhashed files): VERIFIED FIXED** (indexer.py:1103-1106, 1151)
Lines 1103-1106 remove unhashed files from `current_files` after the hashing loop:

```python
for rel in set(current_files) - set(current_hashes):
    del current_files[rel]
```

Line 1151 uses `self._write_meta(current_hashes)` directly instead of the old dict comprehension over `current_files`. Both the KeyError crash and the "unhashed files reappear as new" problem (R10-M2) are fixed.

**R10-M3 (\_extract_name byte offset): VERIFIED FIXED** (indexer.py:314-327)
`_extract_name` now takes `source_bytes: bytes` parameter and uses `source_bytes[start:end].decode("utf-8")` — correctly using byte offsets on the byte string, then decoding to Python str.

**R10-M4 (decorated_definition ambiguity): VERIFIED FIXED** (indexer.py:329-340, 357-377)
New `_find_decorated_inner()` method inspects children of `decorated_definition` nodes, skipping `decorator` and `comment` children to find the actual definition. Lines 357-377 then check whether the inner node is in `_CLASS_LIKE_NODES` or `_FUNCTION_LIKE_NODES`, extracting the name from the inner node. `@dataclass class Foo` now correctly gets `class_name="Foo"` instead of `function_name="Foo"`.

### MAJOR Issues (Remaining/Updated)

**R11-M1 (UPDATED). Main text extraction STILL uses byte offsets as character indices** (indexer.py:352, 420)
While `_extract_name` was fixed to use `source_bytes`, the primary text extraction paths were not:

- Line 352: `text = source[node.start_byte : node.end_byte]` — str sliced by byte offset
- Line 420: `child_text = source[child.start_byte : child.end_byte]` — same issue

These are the MAIN paths that extract the text for every chunk. For files with multi-byte UTF-8 characters, the extracted text will be offset from the actual node content. The fix pattern is the same as `_extract_name`: use `source_bytes[start:end].decode("utf-8")`.

Note: `source_bytes` is already passed to `_collect_chunks()` (line 346) but only used for `_extract_name()` calls. Lines 352 and 420 should use `source_bytes` instead of `source`.

### MINOR Issues (New)

**R12-m1. `is_structural` check forces recursion for ALL top_nodes, even small ones** (indexer.py:425-432)

```python
is_structural = (
    child_type in _FUNCTION_LIKE_NODES
    or child_type in _CLASS_LIKE_NODES
    or child_type in top_nodes
    or child_type == "decorated_definition"
)
if len(child_text) > self.chunk_size or is_structural:
    ...
    self._collect_chunks(child, ...)
```

This forces recursion into every structural child regardless of size. While good for metadata propagation (functions/classes get their own chunks with proper names), it prevents small sibling functions from being merged into a single chunk — each tiny function becomes its own chunk even if it's a one-liner. This increases chunk count and may degrade embedding quality for very small functions. Trade-off is acceptable but worth documenting.

**R12-m2. `_find_decorated_inner` returns first non-decorator non-comment child** (indexer.py:336-340)

```python
for child in node.children:
    child_type: str = child.type
    if child_type != "decorator" and child_type != "comment":
        return child
return None
```

This assumes the first non-decorator, non-comment child is the definition. This is correct for Python's grammar where `decorated_definition` has `decorator* (class_definition | function_definition)`. But it's fragile — if tree-sitter ever adds whitespace or error nodes as children, they'd be returned instead. Using `child_by_field_name("definition")` would be more robust if the grammar supports it.

**R12-m3. `_containers` set still defined inline** (indexer.py:384-387)
Previously flagged as R10-m4. Still created inside `_collect_chunks()` on every recursive call. Should be a module-level `frozenset` constant.

______________________________________________________________________

## Round 13: Search Pipeline, MCP Server, and Metadata Filter Gaps

Audited files:

- `src/vaultspec_rag/search.py` — `parse_query()` (72-90), `search_codebase()` (266-301), `search_all()` (303-310), `SearchResult` dataclass (54-69), `_FILTER_PATTERN` (34), `_FILTER_KEY_MAP` (37-43)
- `src/vaultspec_rag/mcp_server.py` — `search_codebase` tool (127-149), `reindex_codebase` tool (226-247), `SearchResultItem` model (66-82)
- `src/vaultspec_rag/store.py` — `_build_code_filter()` (566-586), `upsert_code_chunks()` (238-283)

### Context

The store now holds `node_type`, `function_name`, and `class_name` in the Qdrant payload for codebase chunks (store.py:272-274). `_build_code_filter()` supports filtering by all five fields: `language`, `path`, `node_type`, `function_name`, `class_name` (store.py:577). The question is whether the search and MCP layers expose this capability to users.

### MAJOR Issues

**R13-M1. `search_codebase()` only passes `language` and `path` filters — ignores `node_type`, `function_name`, `class_name`** (search.py:272-274)

```python
store_filters = {
    k: v for k, v in parsed.filters.items() if k in ("language", "path")
}
```

The store's `_build_code_filter()` supports five filter keys, but `search_codebase()` only passes two. A user who types `node_type:function_definition` or `function:encode_query` or `class:VaultStore` gets no filtering — the filter keys are silently dropped.

**Fix:** Expand the allowlist to include `node_type`, `function_name`, `class_name`:

```python
if k in ("language", "path", "node_type", "function_name", "class_name")
```

**R13-M2. `_FILTER_PATTERN` and `_FILTER_KEY_MAP` don't support the new filter keys** (search.py:34, 37-43)
The regex pattern only matches `type|feature|date|tag|lang|path`. There are no tokens for `node_type`, `function_name`, `class_name`, or shorter aliases. Even if `search_codebase()` accepted them, `parse_query()` would never extract them from user input.

**Fix:** Add filter tokens — e.g., `function:`, `class:`, `node:` or `fn:`, `cls:`, `nt:`. Update `_FILTER_PATTERN` regex and `_FILTER_KEY_MAP`.

**R13-M3. `SearchResult` dataclass has no `node_type`, `function_name`, `class_name` fields** (search.py:54-69)
The dataclass has `language`, `line_start`, `line_end` for code results but no structural metadata. Even though the store returns these fields in the raw result dict, `search_codebase()` (lines 286-300) never extracts them:

```python
SearchResult(
    ...
    language=r.get("language", ""),
    line_start=r.get("line_start"),
    line_end=r.get("line_end"),
    # node_type, function_name, class_name NOT included
)
```

Users can't see what kind of code element (function, class, etc.) each result is, or filter/group by structure in downstream code.

**R13-M4. `SearchResultItem` Pydantic model has no `node_type`, `function_name`, `class_name` fields** (mcp_server.py:66-82)
The MCP Pydantic mirror of `SearchResult` also lacks these fields. MCP clients receive search results without structural metadata. Even if `SearchResult` is updated, `SearchResultItem` must be updated in parallel.

**R13-M5. `reindex_codebase` MCP tool always does `full_index()`** (mcp_server.py:226-247)

```python
async def reindex_codebase(ctx: Context | None = None) -> IndexResponse:
    ...
    result = comp.code_indexer.full_index()
```

Unlike `reindex_vault` which has a `clean` parameter toggling full vs incremental, `reindex_codebase` always does full. The docstring says "always a full re-index." Now that `CodebaseIndexer.incremental_index()` exists, this should offer the same `clean` toggle. Same as R4-M1 from Round 4 — still unfixed.

**R13-M6. `tag` filter parsed but never reaches Qdrant** (search.py:80-81, 229-233)
Previously flagged as M7 in Round 1. Still unfixed. `parse_query()` extracts `tag:` filters (line 80-81) but `search_vault()` only passes `doc_type`, `feature`, `date` (line 232). `_build_filter()` only handles those three keys. The `tag` filter is silently dropped.

### MINOR Issues

**R13-m1. `search_codebase()` uses `path` as `title` for code results** (search.py:292)

```python
title=r["path"],
```

When code results have `function_name` or `class_name` available, a more descriptive title like `"MyClass.my_method"` or `"encode_query()"` would be more useful than the raw file path.

**R13-m2. `search_all()` mixes incompatible score scales** (search.py:303-310)
Previously flagged as M8 in Round 1. `search_vault()` returns graph-boosted scores while `search_codebase()` returns CrossEncoder logits. Sorting them together produces meaningless rankings. Still unfixed.

**R13-m3. MCP `search_codebase` only exposes `language` filter parameter** (mcp_server.py:129-144)
The tool signature has a `language` parameter but no `path`, `node_type`, `function_name`, or `class_name` parameters. Users can only filter by language at the MCP level, while the store supports five filter dimensions.

**R13-m4. No integration tests for codebase search with metadata** (all test files)
Previously flagged as R7-M1, T-C1. There are zero integration tests that:

- Index code files and verify chunks have correct `node_type`/`function_name`/`class_name`
- Search for code and verify results contain structural metadata
- Filter codebase search by `function_name` or `class_name`
  This is the single largest test coverage gap for the new metadata feature.

______________________________________________________________________

## Summary

### Issue Totals (19 Rounds)

| Severity  | Count   |
| --------- | ------- |
| CRITICAL  | 3       |
| MAJOR     | 63      |
| MINOR     | 90      |
| **Total** | **156** |

### Issue Registry (Quick Reference)

**CRITICAL (3):**

- C1: `content.find(text)` line tracking bug (FIXED)
- C2: Chunk ID collision risk (FIXED)
- C3: Missing `incremental_index()` in CodebaseIndexer (FIXED)
- ~~C4: `_stable_id()` 63-bit hash collision risk~~ → downgraded to MINOR (R17)

**MAJOR (58):**

- M1-M10: Core implementation (R1) — M1-M4 FIXED
- T-C1-T-C3, T-M1-T-M7: Test coverage (R2)
- R4-M1-R4-M6: MCP/CLI (R4)
- R5-M1-R5-M4: Public API (R5)
- R6-M1-R6-M3: Dependencies (R6)
- R7-M1-R7-M3: Codebase test gaps (R7)
- R9-C1 (downgraded): O(n\*m) \_get_chunk_ids_for_files perf
- R9-M1-R9-M6: R9 issues — R9-M1, R9-M2, R9-M4, R9-M6, R9-m1 FIXED
- R10-M1-R10-M4: Post-fix issues — R10-M1, R10-M2, R10-M3, R10-M4 ALL FIXED
- R11-M1: Byte offset text extraction (lines 352, 420) — STILL OPEN
- R11-M2: CLI still uses full_index for code
- R13-M1: search_codebase() ignores node_type/function_name/class_name filters
- R13-M2: \_FILTER_PATTERN/\_FILTER_KEY_MAP missing code metadata tokens
- R13-M3: SearchResult dataclass missing code metadata fields
- R13-M4: MCP SearchResultItem missing code metadata fields
- R13-M5: reindex_codebase MCP tool always calls full_index() (=R4-M1)
- R13-M6: tag filter parsed but never reaches Qdrant (=M7 from R1)
- R14-M1: **init**.py missing CodebaseIndexer and CodeChunk exports
- R14-M2: api.py has no codebase API facade (no index_codebase/search_codebase)
- R14-M3: api.py \_Engine lacks VaultSearcher — no search() in public API
- R14-M4: api.py list_documents() O(n) individual Qdrant retrievals
- R15-M1: Duplicate test files test_query.py and test_search_unit.py
- R15-M2: No integration tests for search_codebase() (=R7-M1/R13-m4)
- R15-M3: test_upsert_code_chunks never tests sparse vectors
- R17-M1: encode_query_sparse() does not truncate to max_chars
- R17-M2: No OOM handling for GPU embedding batches
- R17-M3: get_config() creates new wrapper on every call (no caching)
- R18-M1: .gt check runs before .git and takes priority — false positive risk
- R19-M1: search_codebase MCP injects language via query mutation (fragile)
- R20-M1: Zero integration tests for CodebaseIndexer (CRITICAL GAP)
- R20-M2: Zero integration tests for search_codebase() (CRITICAL GAP)
- R20-M3: \_build_rag_components creates only VaultIndexer, no CodebaseIndexer
- R20-M4: test_store_codebase tests upsert without sparse vectors
- R20-M5: test_query.py entirely redundant with test_search_unit.py (=R15-M1)
- R20-M6: test_robustness.py has 4 unit tests disguised as robustness tests
- R20-M7: test_embeddings.py in unit dir but marked integration

______________________________________________________________________

## Round 14 — Cross-Module Audit: api.py, config.py, embeddings.py, cli.py, workspace.py, **init**.py

**Focus:** Audit remaining modules not yet deeply covered. Look for public API gaps,
config inconsistencies, embeddings edge cases, CLI bugs, and export mismatches.

### Findings

**R14-M1. `__init__.py` missing `CodebaseIndexer` export** (**init**.py:9-36)
The public `__init__.py` exports `VaultIndexer` and `IndexResult` but NOT `CodebaseIndexer`.
Any consumer doing `from vaultspec_rag import CodebaseIndexer` gets `ImportError`. The CLI
and MCP server both import it directly from `.indexer`, but downstream users of the package
API cannot access it through the top-level namespace. `CodeChunk` from store.py is also missing.

**R14-M2. `api.py` has no codebase API facade** (api.py)
The `api.py` module provides `index()`, `list_documents()`, `get_related()` — all vault-only.
There is no `index_codebase()`, `search_codebase()`, or `search_vault()` function in the
public API facade. The `_Engine` class creates only a `VaultIndexer`, not a `CodebaseIndexer`
or `VaultSearcher`. Any programmatic consumer (not using CLI or MCP) has no simple entry point
for codebase features.

**R14-M3. `api.py` `_Engine` lacks `VaultSearcher`** (api.py:30-38)
The `_Engine` singleton creates `store`, `model`, and `indexer` but NOT a `VaultSearcher`.
There is no `search()` function in the public API facade at all. The `search` module is
exported from `__init__.py` but only as individual classes — no facade function wraps them.

**R14-M4. `api.py` `list_documents()` is O(n) individual retrievals** (api.py:85-97)
`list_documents()` calls `store.get_by_id(doc_id)` in a loop for every ID returned by
`get_all_ids()`. Each call does a separate Qdrant `retrieve()` RPC. For a vault with 200+
docs, this is 200+ round trips. Should use `_client.scroll()` with `with_payload=True` to
fetch all documents in batches.

**R14-m1. `config.py` uses bare `Any` return type** (config.py:9, 21)
`from typing import Any` is imported and `__getattr__` returns `-> Any`. The CLAUDE.md says
"strict typing (no bare `Any`)". However, this is a dynamic proxy pattern where the return
type genuinely depends on the attribute name, so this is a borderline case — noted but
low priority.

**R14-m2. `embeddings.py` `encode_documents()` truncates by characters, not tokens** (embeddings.py:231)
`truncated = [t[:max_chars] for t in texts]` slices by character count (default 8000).
The actual model context limit is in tokens (typically ~8192 for Qwen3). Character truncation
is an approximation that works for most content but could truncate mid-token for dense code
or pass too-long sequences for languages with short characters. Minor because 8000 chars is
conservative for most token-based limits.

**R14-m3. `embeddings.py` sparse batch_size defaults differ from dense** (embeddings.py:262 vs 214)
`encode_documents()` uses `_default_batch_size()` (configurable, default 64) but
`encode_documents_sparse()` hardcodes `batch_size: int = 32`. These should be consistent
or the sparse default should also come from config.

**R14-m4. `cli.py` handle_index summary table shows `c_res.added/updated/removed`** (cli.py:230-238)
The summary table renders `c_res.added`, `c_res.updated`, `c_res.removed` for codebase
indexing — but `full_index()` only sets `total`, `files`, and `duration_ms` meaningfully.
`added`/`updated`/`removed` are only populated by `incremental_index()`. For `full_index()`,
these will be 0 or misleading. Once Task #18 wires incremental, this becomes correct — but
currently the table shows zeros for code.

**R14-m5. `workspace.py` `discover_git()` checks for `.gt/` container** (workspace.py:106-122)
This checks for a `.gt` directory as a container root. The `.gt` convention is uncommon and
not documented anywhere in this project's docs or ADRs. If this is a vaultspec-specific
convention, it should be documented. If it's dead code, it should be removed.

**R14-m6. `cli.py` `handle_search` creates new `VaultStore` and `EmbeddingModel` per call** (cli.py:263-265)
Every search command instantiation creates brand-new Store and EmbeddingModel instances. The
EmbeddingModel constructor loads two neural networks onto GPU (~2-4 seconds). For a CLI tool
this is unavoidable (each invocation is a new process), but worth noting for any future
interactive/REPL mode.

**R14-m7. `_build_filter()` silently ignores unknown filter keys** (store.py:538-564)
If `search_vault()` passes a filter dict with keys not in `("date", "doc_type", "feature")`,
`_build_filter()` silently drops them. The `tag` filter from `parse_query()` falls into this
silent-drop category. Same pattern in `_build_code_filter()` at line 566-586, though there
the allowed set is broader.

**R14-m8. `rerank_with_graph()` reranks AFTER `_rerank()` CrossEncoder** (search.py:262-264)
In `search_vault()`, CrossEncoder reranking happens first (line 262), then graph reranking
(line 264). The graph boost multiplies CrossEncoder scores, which means graph influence
depends on the CrossEncoder score scale. If the CrossEncoder returns small scores, the
1.0 + 0.1\*links multiplier has outsized relative effect. This ordering is likely intentional
but the interaction between two reranking stages is non-obvious.

______________________________________________________________________

## Round 15 — Test Coverage Audit + Task #18 Verification

**Focus:** Audit all test files for coverage gaps, duplicate tests, missing markers, and
compliance with CLAUDE.md. Verify Task #18 (incremental codebase indexing in CLI/MCP).

### Task #18 Verification: CONFIRMED FIXED

CLI `handle_index` (cli.py:205-208) now does:

```python
c_res = c_indexer.full_index() if clean else c_indexer.incremental_index()
```

MCP `reindex_codebase` (mcp_server.py:226-244) now has `clean: bool = False` parameter
and toggles between `full_index()` and `incremental_index()`.

Previously flagged issues now resolved:

- R11-M2 (CLI uses full_index for code) — FIXED
- R13-M5 (MCP reindex_codebase always full_index) — FIXED
- R4-M1 (no incremental option in MCP) — FIXED

### Findings

**R15-M1. Duplicate test coverage: `test_query.py` and `test_search_unit.py`**
Both files test `parse_query()` with overlapping test cases:

- `test_query.py::TestQueryParsing` — 6 tests (plain, type, multiple, date, tag, filter-only)
- `test_search_unit.py::TestParseQuery` — 13 tests (superset: adds lang, path, empty, hash
  strip, space collapse, unknown prefix)
  `test_query.py` is entirely redundant — every case it tests is covered by
  `test_search_unit.py`. Should be deleted to reduce noise and confusion.

**R15-M2. No integration tests for `search_codebase()`** (all test files)
`test_search_integration.py::TestVaultSearch` has 5 tests — all call `searcher.search()`
or `searcher.search_vault()`. Zero tests call `searcher.search_codebase()`.
The codebase search pipeline (encode -> hybrid_search_codebase -> \_rerank) has no
end-to-end test with real indexed code. Previously flagged as R7-M1/R13-m4.

**R15-M3. `test_store_codebase.py` `test_upsert_code_chunks` doesn't test sparse vectors**
(test_store_codebase.py:30-49)
The test creates a `CodeChunk` with only a dense `vector` — no `sparse_indices`/`sparse_values`.
This means the sparse vector upsert branch (store.py:256-259) is never exercised in tests.

**R15-m1. `test_store_codebase.py` is marked `integration` but `test_build_code_filter` is unit**
(test_store_codebase.py:51-61)
The file has `pytestmark = [pytest.mark.integration]` but `test_build_code_filter` calls only
static `VaultStore._build_code_filter()` — no GPU, no Qdrant, no model. It should be in a
unit-marked class or moved to `test_store.py`.

**R15-m2. `test_api_integration.py` tests have redundant `@pytest.mark.integration` markers**
(test_api_integration.py:22, 42, 80, etc.)
The file has `pytestmark = [pytest.mark.integration]` at module level, but individual methods
also have `@pytest.mark.integration`. The module-level marker already applies to all tests,
so the method-level duplicates are noise. (Tests marked `@pytest.mark.quality` do need explicit
markers to override, so those are correct.)

**R15-m3. `conftest.py` `_build_rag_components` only creates `VaultIndexer`, not `CodebaseIndexer`**
(conftest.py:78-124)
The `rag_components` fixture indexes vault docs but never creates a `CodebaseIndexer` or
indexes any code. Any integration test wanting to test codebase features must set up its own
`CodebaseIndexer` — but none do. This is the root cause of R15-M2.

**R15-m4. `test_embeddings.py` uses `hasattr()` checks instead of type assertions**
(test_embeddings.py:69-77)
Tests like `assert hasattr(sparse_vecs[0], "indices")` are weak — they pass for any object
with an `indices` attribute. Should assert `isinstance(sparse_vecs[0], SparseResult)` or
check actual values.

**R15-m5. No test for `workspace.py` `resolve_workspace()`**
There are no tests for the workspace resolution logic — `discover_git()`, `_walk_up_for_git()`,
`_parse_git_pointer()`, `_strip_unc()`. These are complex path-manipulation functions with
multiple branches (worktree detection, `.gt` container, UNC path stripping) and no test coverage.

______________________________________________________________________

## Round 16 — Re-audit indexer.py after coder changes (+666 lines diff)

**Focus:** Re-read indexer.py after significant coder changes. Verify previously flagged
fixes and identify any new issues or regressions.

### Verified Fixes (this round)

- **c_sharp grammar name** (API verification report): Line 172 now reads
  `".cs": ("csharp", "csharp")` and line 218 uses `"csharp":` key. FIXED.
- **R10-m4 (`_containers` inline set)**: Now `_CONTAINER_NODES` module constant (line 266).
  FIXED.
- **R10-M4 (decorated_definition)**: `_find_decorated_inner()` present (line 340-351). FIXED.
- **R9-M2 (name extraction byte offset)**: `_extract_name()` (line 324-338) now correctly
  uses `source_bytes` for byte offsets and `.decode("utf-8")`. FIXED.
- **R9-M4 (missing source_bytes parameter)**: `_collect_chunks` now receives `source_bytes`
  (line 357). FIXED.
- **R9-M6 (metadata not propagated)**: 6-tuple output includes all three metadata fields. FIXED.
- **Chunk ID stability**: Uses `sha256(text)[:12]` hash (lines 968, 1008). FIXED.

### Still Open

**R11-M1. Byte offset as character index** (indexer.py:363, 425) — STILL OPEN
`source[node.start_byte : node.end_byte]` where `source` is `str` but offsets are byte
positions. Diverges for non-ASCII source.

**R9-C1 (downgraded). O(n\*m) `_get_chunk_ids_for_files`** (indexer.py:1173-1181) — STILL OPEN
Task #24 pending.

### New Findings

**R16-m1. `full_index()` reads each file twice** (indexer.py:1028-1041)
Files are hashed at lines 1028-1034 by `p.read_bytes()`, then read again at line 927
(`path.read_text()`) inside `_chunk_file()`. Disk cache makes this fast, but a single-read
pattern would be cleaner.

**R16-m2. `incremental_index()` `files` counts re-indexed, not scanned** (indexer.py:1170)
`files=len(to_index)` counts only files that were re-indexed, while `full_index()` returns
`files=len(paths)` (total scanned). Naming ambiguity — minor.

**R16-m3. TextSplitter `content.find(text)` fallback can find wrong match** (indexer.py:998-1000)
When `search_offset` tracking fails (`idx == -1`), the fallback `content.find(text)` at
line 1000 restarts from position 0, potentially finding an earlier duplicate. Same class of
bug as the original C1 but only affects the TextSplitter fallback path (non-AST languages).

### Verified fixes (cumulative)

Issues confirmed fixed across all rounds:

- C1, C2, C3: Core indexer bugs (Task #3)
- M1-M4: Core implementation (Task #3)
- R9-M1, R9-M2, R9-M4, R9-M6, R9-m1: Round 9 bugs (Task #13)
- R10-M1, R10-M2, R10-M3, R10-M4: Post-fix regressions (Task #19)
- R10-m4: \_containers inline set →\_CONTAINER_NODES module constant
- R11-M2: CLI full_index for code (Task #18)
- R13-M5: MCP reindex_codebase full_index only (Task #18)
- R4-M1: No incremental option in MCP (Task #18)
- c_sharp grammar name: both LANGUAGE_MAP and \_TOP_LEVEL_NODES

### Open themes (unresolved)

1. R11-M1: Byte offset as character index (indexer.py:363, 425) — still open
1. R13-M1-M4: Search pipeline metadata gap — Task #22 in progress
1. R13-M6/M7/R14-m7: Tag filter parsed but silently dropped
1. R14-M1-M3: Public API facade vault-only — Task #25 pending
1. R14-M4: list_documents O(n) retrieval — Task #26 pending
1. R15-M2: No codebase search integration tests
1. C4: \_stable_id() 63-bit hash collision risk
1. R9-C1: O(n\*m) \_get_chunk_ids_for_files — Task #24 pending

______________________________________________________________________

## Round 17 — Deep Audit: embeddings.py, config.py, \_stable_id(), byte offsets

**Focus:** Deep-dive into embedding pipeline, config validation, `_stable_id()` collision
math, and exhaustive byte/char offset analysis.

### 1. Byte/Char Offset — Exhaustive Analysis

All uses of `start_byte`/`end_byte` in the codebase:

| Line | Expression                                              | Object sliced | Status           |
| ---- | ------------------------------------------------------- | ------------- | ---------------- |
| 337  | `source_bytes[name_node.start_byte:name_node.end_byte]` | `bytes`       | CORRECT          |
| 363  | `source[node.start_byte:node.end_byte]`                 | `str`         | **BUG (R11-M1)** |
| 425  | `source[child.start_byte:child.end_byte]`               | `str`         | **BUG (R11-M1)** |

The fix for lines 363 and 425 should be:

```python
text = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
```

This matches the pattern already used at line 337 for name extraction.

### 2. `_stable_id()` Collision Analysis

**Implementation** (store.py:589-598):

```python
h = hashlib.sha256(string_id.encode("utf-8")).digest()
return int.from_bytes(h[:8], byteorder="big") & 0x7FFFFFFFFFFFFFFF
```

This produces a 63-bit integer (max 9.2 × 10^18).

**Birthday paradox collision probability:**

| Scale              | P(collision) | Verdict    |
| ------------------ | ------------ | ---------- |
| 1K docs            | 5.4 × 10^-14 | Negligible |
| 10K docs           | 5.4 × 10^-12 | Negligible |
| 100K docs + chunks | 5.4 × 10^-10 | Safe       |
| 1M total points    | 5.4 × 10^-8  | Safe       |
| 10M total points   | 5.4 × 10^-6  | Low risk   |
| 4.3B total points  | ~50%         | Dangerous  |

**Verdict:** C4 severity was originally CRITICAL. Downgrading to MINOR. At any realistic
scale for a vault workspace (< 1M total points combining docs + code chunks), the collision
probability is below 1 in 10 million. A true collision would silently overwrite one point
with another (data loss), but the probability at our scale is negligible.

**R17-downgrade-C4:** C4 downgraded from CRITICAL to MINOR.

### 3. Embeddings Pipeline Deep Audit

**R17-M1. `encode_query_sparse()` does not truncate to max_chars** (embeddings.py:282-293)
`encode_documents_sparse()` truncates to `max_chars` at line 273-274, and `encode_documents()`
truncates at line 230-231. But `encode_query_sparse()` at line 291 passes the raw query
directly: `self._sparse_model.encode([query])`. If a user submits a very long query, SPLADE
receives untrimmed input. `encode_query()` (dense) also does not truncate, but queries are
typically short. However, `search_all()` could receive a pasted code block as a query. The
asymmetry between documents (truncated) and queries (not truncated) is inconsistent.

**R17-M2. No OOM handling for GPU embedding batches** (embeddings.py:233-238, 276-279)
If a batch of documents exceeds GPU VRAM (e.g. 500 long documents at batch_size=64),
`SentenceTransformer.encode()` and `SparseEncoder.encode()` will raise `torch.cuda.OutOfMemoryError`
which propagates unhandled to the caller. The indexer's `full_index()` and `incremental_index()`
have no try/except for OOM. A single OOM crashes the entire indexing run with no partial
progress saved.

**R17-m1. Dense model `torch_dtype` uses object, sparse uses string** (embeddings.py:170, 189)
Dense: `model_kwargs={"torch_dtype": torch.float16}` (torch dtype object)
Sparse: `model_kwargs={"torch_dtype": "float16"}` (string)
Both work because sentence-transformers accepts both forms, but the inconsistency is notable.

**R17-m2. `encode_documents()` does not use `prompt_name` for documents** (embeddings.py:233)
Qwen3-Embedding supports instruction-based encoding where documents and queries receive
different prompts. `encode_query()` correctly uses `prompt_name="query"` (line 256) but
`encode_documents()` uses no `prompt_name`. This is CORRECT for Qwen3's design — the model's
default prompt is for documents/passages. Noted for documentation, not a bug.

### 4. Config Deep Audit

**R17-M3. `get_config()` creates new wrapper on every call** (config.py:55-58)
`get_config()` calls `get_base_config(overrides)` and wraps it in a new
`VaultSpecConfigWrapper` every time. The `rag_defaults` dict inside `__getattr__` is also
recreated on every attribute access. This means every config lookup does:

1. Call `get_base_config()` (may or may not cache internally)
1. Create new `VaultSpecConfigWrapper`
1. On attribute access, create new `rag_defaults` dict
1. Try `getattr(self._base, name)`, catch `AttributeError`, return default

For hot paths like `_default_batch_size()` called per batch, this is wasteful. The wrapper
should be a singleton or the defaults dict should be a class variable.

**R17-m3. `hasattr(cfg, "sparse_model")` guard is meaningless** (embeddings.py:163-166)

```python
sparse_name = (
    cfg.sparse_model
    if hasattr(cfg, "sparse_model") and cfg.sparse_model
    else self.SPARSE_MODEL_NAME
)
```

The wrapper's `__getattr__` always returns a value for `"sparse_model"` (it's in
`rag_defaults`), so `hasattr()` is always `True`. The `and cfg.sparse_model` check catches
the case where the base config explicitly sets it to `""` or `None`, but the `hasattr` part
is dead code. Same issue at line 193-196 with `hasattr(cfg, "embedding_dimension")`.

**R17-m4. No config validation — bad values pass silently** (config.py:21-44)
The wrapper provides defaults but never validates types or ranges. If the base config has
`embedding_batch_size: "not_a_number"`, it passes through to `SentenceTransformer.encode()`
which will fail with an obscure error. Minimum validation (type checks for numeric configs,
non-empty string for model names) would catch misconfigurations early.

______________________________________________________________________

## Round 18 — Tag Filter Root Cause Trace, Task #21 Verification, workspace.py, CLI errors

**Focus:** End-to-end tag filter trace, verify Task #21 (tautological tests), audit
workspace.py `.gt` convention, and CLI error message quality.

### Task #21 Verification: CONFIRMED FIXED

The `test_returns_doc_for_audit_dir` test (test_indexer_unit.py:98-107) was the primary
tautological test. Old code had nested `if audit_files:` and `if doc is not None:` guards
that made assertions conditional. New code:

```python
assert len(audit_files) > 0, "test-project must contain audit/*.md files"
doc = prepare_document(audit_files[0], TEST_PROJECT)
assert doc is not None, f"prepare_document returned None for {audit_files[0]}"
assert doc.doc_type == "audit"
```

No remaining conditional assertions found in test_indexer_unit.py. The `if c[4] is not None`
patterns at lines 891/901/908 are list comprehension filters, not conditional test assertions.

### Tag Filter Bug — Complete End-to-End Trace

This bug has been flagged as M7 (R1), R13-M6, and R14-m7 across multiple rounds.
Here is the full execution trace:

**Step 1: User query** `"tag:#research embedding models"`

**Step 2: `parse_query()` (search.py:72-90)**
The regex `_FILTER_PATTERN` matches `tag:#research`. At line 80-81:

```python
if key == "tag":
    filters["tag"] = value.lstrip("#")  # → "research"
```

`"tag"` is NOT in `_FILTER_KEY_MAP` (which only has type/feature/date/lang/path),
so it goes through the special `if key == "tag"` branch. Result:
`ParsedQuery(text="embedding models", filters={"tag": "research"})`

**Step 3: `search_vault()` (search.py:229-233)**

```python
store_filters = {
    k: v for k, v in parsed.filters.items()
    if k in ("doc_type", "feature", "date")
}
```

The filter dict is `{"tag": "research"}`. The key `"tag"` is NOT in
`("doc_type", "feature", "date")`, so **`store_filters` is empty `{}`**.

**Step 4: `hybrid_search()` (store.py:411)**
`store_filters or None` → `None`. `_build_filter(None)` returns `None`.
No filter is applied — the query searches ALL documents as if `tag:` was never specified.

**Step 5: Result** — The tag filter is silently ignored. The user gets unfiltered results
and may not realize their `tag:#research` constraint was dropped.

**Root causes (three separate gaps):**

1. **search.py:229-233** — `search_vault()` whitelist only passes `doc_type`, `feature`,
   `date`. It does not pass `tag`. This is the PRIMARY drop point.

1. **store.py:538-564** — Even if `tag` reached `_build_filter()`, it would be silently
   dropped because the method only handles `doc_type`, `feature`, `date`. This is the
   SECONDARY drop point.

1. **store.py payload** — The vault document payload (line 218-228) stores `tags` as a
   list field. To filter by a single tag, the filter would need to use
   `models.MatchAny(any=[tag])` on the `tags` list field, not `MatchValue`. The filter
   type is wrong even if the key were passed through.

**Fix requires three changes:**

1. `search_vault()` line 232: add `"tag"` to the whitelist
1. `_build_filter()`: add a `tag` handler that uses `MatchAny` on the `tags` list field
1. Verify the Qdrant `tags` payload field stores list values (confirmed at line 224)

### workspace.py `.gt` Convention — Deep Audit

**R18-M1. `.gt` check runs BEFORE `.git` check and takes priority** (workspace.py:107-122)
`discover_git()` checks for `.gt/` first (lines 107-122), walking all the way up to the
filesystem root. Only if no `.gt/` is found does it fall through to the `.git` check
(line 124). This means:

1. If any ancestor directory happens to have a `.gt/` folder (e.g. a Go test directory,
   a temp folder, a user-created directory), it will be detected as a "container root"
   and the function returns `is_bare=True` with that directory as `repo_root`.
1. The actual `.git` directory is never checked.
1. This could cause `resolve_workspace()` to use the wrong directory as `target_dir`,
   leading to indexing the wrong files, missing the vault, or other workspace errors.

The `.gt` convention is not part of standard git. It's not documented in any ADR or doc
in this project. It may come from the vaultspec core library. If it's needed, it should
be documented. If not, it's a false-positive risk.

**R18-m1. `discover_git()` returns `None` if `.git` file has unparseable content**
(workspace.py:140-142)
If `.git` is a file (worktree pointer) but `_parse_git_pointer()` returns `None` (bad
format), `discover_git()` returns `None` entirely — even though a `.git` file exists.
The fallback `resolve_workspace()` then uses `cwd` as root with `git=None`, which means
workspace resolution succeeds but thinks there's no git repo. This could cause subtle
issues with path resolution.

### CLI Error Message Audit

**R18-m2. `handle_index` does not catch GPU-related errors** (cli.py:160-211)
If `EmbeddingModel()` raises `RuntimeError("CUDA GPU required")`, the error propagates
as a raw traceback. The CLI should catch this and show a user-friendly message like
"Error: No CUDA GPU found. GPU is required for indexing."

**R18-m3. `handle_search` does not catch GPU errors either** (cli.py:262-290)
Same issue — `EmbeddingModel()` at line 264 can raise RuntimeError, producing a raw
traceback instead of a user-friendly error.

**R18-m4. `handle_status` does not handle missing torch gracefully** (cli.py:299)
`import torch` at line 299 is inside the command function, not guarded. If torch is not
installed, the user gets a raw `ModuleNotFoundError` traceback instead of a helpful message.

______________________________________________________________________

## Round 19 — MCP Server Tool Schema Audit

**Focus:** Verify input/output types, consistency, and correctness of all MCP tool schemas.

### Tool Schema Summary

| Tool               | Sync/Async | Input Types                                          | Return Type      | Schema OK? |
| ------------------ | ---------- | ---------------------------------------------------- | ---------------- | ---------- |
| `search_vault`     | async      | `query: str, top_k: int=5`                           | `SearchResponse` | OK         |
| `search_codebase`  | async      | `query: str, top_k: int=5, language: str\|None=None` | `SearchResponse` | Issues     |
| `search_all`       | async      | `query: str, top_k: int=5`                           | `SearchResponse` | OK         |
| `get_index_status` | sync       | (none)                                               | `IndexStatus`    | OK         |
| `get_code_file`    | sync       | `path: str`                                          | `str`            | Issues     |
| `reindex_vault`    | async      | `clean: bool=False`                                  | `IndexResponse`  | Minor      |
| `reindex_codebase` | async      | `clean: bool=False`                                  | `IndexResponse`  | OK         |

### Findings

**R19-M1. `search_codebase` injects `language` via query string mutation** (mcp_server.py:143-144)

```python
if language:
    query = f"lang:{language} {query}"
```

Instead of passing `language` directly to the store as a filter, it prepends `lang:{language}`
to the query string and relies on `parse_query()` to re-extract it. This works but:

- The language value is embedded then re-parsed, which is fragile
- If the user's query already contains `lang:X`, it would create two conflicting lang filters
- The query text is polluted with `lang:python` before being embedded — the dense encoder
  sees "lang:python" as literal text, slightly degrading embedding quality
- Should instead pass `language` directly to `search_codebase()` as a filter parameter

**R19-m1. `get_code_file` returns plain `str`, not a Pydantic model** (mcp_server.py:178-194)
All other tools return Pydantic models (`SearchResponse`, `IndexStatus`, `IndexResponse`).
`get_code_file` returns a raw `str`. MCP clients expecting structured output will get
inconsistent response shapes. The error cases also return plain strings like
`"Error: path 'x' is outside the workspace."` — no structured error model.

**R19-m2. Mixed sync/async tool definitions** (mcp_server.py)
`get_index_status` (line 168) and `get_code_file` (line 179) are sync functions.
`search_vault`, `search_codebase`, `search_all`, `reindex_vault`, `reindex_codebase` are
async. FastMCP handles both, but the inconsistency is unnecessary — the sync tools don't
do any blocking I/O that would benefit from being sync vs async.

**R19-m3. `reindex_vault` response omits `files` field** (mcp_server.py:217-223)
`reindex_codebase` includes `files=result.files` (line 252) but `reindex_vault` does not.
The `IndexResponse` defaults `files=0`, so the response is valid but inconsistent.
`VaultIndexer.full_index()` sets `files=0` (no file count for vault), so this is technically
correct — vault indexing counts documents not files. But the schema allows `files` and
returns 0 for vault, which could confuse clients.

**R19-m4. `SearchResultItem.model_validate(r, from_attributes=True)` double-specified**
(mcp_server.py:122, 147, 162)
The `from_attributes=True` kwarg is passed to `model_validate()`, but it's also set in the
model's `model_config = {"from_attributes": True}`. Redundant but harmless.

**R19-m5. `get_code_file` path traversal check may fail on Windows** (mcp_server.py:186-187)

```python
full_path = (comp.root_dir / path).resolve()
if not full_path.is_relative_to(comp.root_dir.resolve()):
```

On Windows, `resolve()` can produce UNC paths (`\\?\...`) depending on path length.
`is_relative_to()` may fail to match if one path has UNC prefix and the other doesn't.
The workspace module has `_strip_unc()` but it's not used here.

______________________________________________________________________

## Round 20: Integration Test Suite Deep Audit

Audited all 7 integration test files, 3 conftest files, 8 unit test files.
Goal: identify coverage gaps, disguised unit tests, fixture issues, and missing scenarios.

### Test Inventory

| File                                      | Marker                | Tests | Real GPU/Qdrant? |
| ----------------------------------------- | --------------------- | ----- | ---------------- |
| `integration/test_indexer_integration.py` | integration + quality | 7     | Yes              |
| `integration/test_search_integration.py`  | integration           | 11    | Yes              |
| `integration/test_api_integration.py`     | integration + quality | 11    | Yes              |
| `integration/test_store_integration.py`   | integration           | 5     | Yes (4 of 5)     |
| `integration/test_quality.py`             | quality               | 13    | Yes              |
| `integration/test_performance.py`         | performance           | 10    | Yes              |
| `integration/test_robustness.py`          | robustness            | 7     | Partial          |
| `test_embeddings.py`                      | integration           | 7     | Yes              |
| `test_store_codebase.py`                  | integration           | 4     | Yes (3 of 4)     |
| `test_search_unit.py`                     | unit + integration    | ~16   | 3 integration    |
| `test_indexer_unit.py`                    | unit                  | ~40   | No               |
| `test_store.py`                           | unit                  | 7     | No               |
| `test_query.py`                           | unit                  | 6     | No               |
| `test_cli.py`                             | unit                  | 13    | No               |
| `test_mcp_server.py`                      | unit                  | 14    | No               |

Total: ~171 tests across 15 files.

### Findings

**R20-M1. Zero integration tests for CodebaseIndexer** (CRITICAL GAP)
`test_indexer_integration.py` tests only `VaultIndexer` (full_index, incremental_index,
prepare_document). There are no integration tests for `CodebaseIndexer.full_index()`,
`CodebaseIndexer.incremental_index()`, or `CodebaseIndexer._chunk_file()` with real GPU
embeddings. The unit tests in `test_indexer_unit.py` test `ASTChunker` and `_chunk_with_ast`
without GPU, but no test exercises the full pipeline: scan → chunk → embed → upsert → query.

**R20-M2. Zero integration tests for `search_codebase()`** (CRITICAL GAP)
`test_search_integration.py` has 11 tests — all for `VaultSearcher.search()` (vault search).
No test calls `VaultSearcher.search_codebase()` or `search_all()`. The entire codebase
search pipeline (embedding → hybrid search → reranking) is untested end-to-end.

**R20-M3. `_build_rag_components` creates only VaultIndexer, no CodebaseIndexer** (conftest.py:78-124)
The test fixture builds `VaultIndexer` and indexes vault docs. It does not create a
`CodebaseIndexer` or index any code. This means no integration test can exercise codebase
search unless it builds its own fixture — none currently do.

**R20-M4. `test_store_codebase.py` tests upsert without sparse vectors** (test_store_codebase.py:30-49)
`test_upsert_code_chunks` creates a `CodeChunk` with only `vector` (dense). The `sparse_indices`
and `sparse_values` fields default to empty lists. The upsert succeeds but does not test the
hybrid search path (SPLADE + dense). The actual `CodebaseIndexer` always provides sparse
vectors. This is a fidelity gap — the test doesn't match real usage.

**R20-M5. `test_query.py` is entirely redundant with `test_search_unit.py`** (DUPLICATE)
`test_query.py` has 6 tests (plain, type, multiple, date, tag, filter-only).
`test_search_unit.py::TestParseQuery` has 13 tests that are a strict superset — same
assertions plus lang, path, empty, tag-strips-hash, collapses-spaces, unknown-prefix.
`test_query.py` should be deleted to avoid confusion.

**R20-M6. `test_robustness.py` has 4 tests that are unit tests in disguise** (robustness marker misuse)
Lines 63-142: `test_unicode_content_in_parser`, `test_feature_key_frontmatter_parsed`,
`test_content_with_embedded_yaml_separators`, `test_content_with_code_block_yaml_separators`
These call `parse_vault_metadata()` with hardcoded strings — no GPU, no Qdrant, no real
files. They should be marked `@pytest.mark.unit`, not `@pytest.mark.robustness`.
The `robustness` marker implies real hardware + edge-case inputs per CLAUDE.md.

**R20-M7. `test_embeddings.py` marked `integration` but belongs in integration/ directory**
The file is at `tests/test_embeddings.py` (unit test directory) but marked `integration`.
It requires real GPU + EmbeddingModel. Should live in `tests/integration/test_embeddings.py`
for consistency with the directory convention.

**R20-m1. Double marker on many integration tests** (minor)
`test_indexer_integration.py` has `pytestmark = [pytest.mark.integration]` at module level
AND `@pytest.mark.integration` on individual tests. The decorator is redundant.

**R20-m2. `test_api_integration.py` tests bypass the API facade** (test fidelity)
Tests in `TestRAGAPI` claim to test the "public API facade" but most (lines 22-54) create
`VaultSearcher` directly from `rag_components` rather than calling `vaultspec_rag.search()`,
`vaultspec_rag.index()`, etc. Only `test_index_incremental`, `test_index_full`,
`test_list_documents*`, and `test_get_related` actually call the API functions. The search
tests should use the API facade, not bypass it.

**R20-m3. `test_store_integration.py::test_search_empty_store` creates a second EmbeddingModel**
(line 69)
This test creates `EmbeddingModel()` outside the session fixture. On a GPU with limited
VRAM, this could cause OOM if the model is loaded twice. Should use `rag_components["model"]`.

**R20-m4. `test_performance.py::test_parse_query_latency` needs no GPU** (marker misuse)
This test calls `parse_query()` 100 times — pure CPU regex. Marked `performance` which
requires GPU per convention. Should be `unit`.

**R20-m5. Session fixtures don't create a VaultSearcher** (conftest.py)
Each integration test creates its own `VaultSearcher(root, model, store)` — repeated ~20
times across test files. The session fixture should provide a pre-built searcher.

**R20-m6. No test for `tag:` filter actually working end-to-end** (coverage gap)
`test_query.py` and `test_search_unit.py` verify `parse_query("tag:research")` extracts the
filter. But no integration test verifies that the filter reaches Qdrant and actually narrows
results. Since we know from R18 that the tag filter is silently dropped, there should be a
failing test to catch this — there isn't one.

**R20-m7. No integration test for CrossEncoder reranker on codebase results**
`test_search_unit.py::TestRerank` tests `_rerank` on vault results. No test verifies
CrossEncoder reranking on codebase search results.

**R20-m8. No test for `search_all()` mixed-source ranking**
`search_all()` combines vault and codebase results. No integration test verifies that
combined results are correctly ranked (known issue R1-M8: different score scales).

### Critical Happy-Path Scenarios with Zero Coverage

1. **Codebase full pipeline**: Scan files → AST chunk → embed on GPU → upsert to Qdrant →
   search_codebase → verify relevant code chunks returned
1. **Codebase incremental index**: Index code → modify a file → incremental_index →
   verify only changed file re-embedded
1. **search_all()**: Index vault + code → search_all → verify mixed results from both sources
1. **Tag filter end-to-end**: Index docs with tags → search with `tag:X` → verify filtering
1. **Code metadata filters**: Index code → search with `func:X` or `class:Y` → verify
   filtering by function_name/class_name
1. **MCP tools end-to-end**: Call `search_codebase`, `reindex_codebase` via MCP → verify
   correct responses

### Fixture Issues That Could Cause Silent Failures

1. **No CodebaseIndexer in session fixture** (R20-M3): Any test attempting to test codebase
   search would need its own fixture, making it appear like a test gap rather than a fixture gap
1. **`test_search_empty_store` loads duplicate model** (R20-m3): Could OOM on smaller GPUs
1. **Session fixture cleanup is best-effort** (conftest.py:140-142): `shutil.rmtree` in
   teardown — if Qdrant has the directory locked, cleanup fails silently
1. **`_vault_snapshot_reset` runs `git checkout`** (conftest.py:184-192): If tests modify
   vault files, this resets them. But it's `check=False` — silent failure if git isn't available

### Summary — Round 20

| Severity | Count | Key Items        |
| -------- | ----- | ---------------- |
| MAJOR    | 7     | R20-M1 to R20-M7 |
| MINOR    | 8     | R20-m1 to R20-m8 |

**Running totals: 3C, 70M, 98m = 171 issues across 20 rounds**
