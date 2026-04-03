---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
related: []
---

# Round 27 Audit -- Final Sweep (__init__.py, mcp_server.py second pass, root conftest.py)

## __init__.py

### R27-PASS: Exports are complete and correct

All 17 exports in `__all__` match real symbols in their source modules. The import chain (`__init__.py` -> `api.py` -> `embeddings.py`, `store.py`, etc.) does NOT trigger GPU checks at import time -- `_check_rag_deps` is only called inside `EmbeddingModel.__init__` and `VaultStore.__init__`. So `import vaultspec_rag` works on machines without CUDA (operations fail at runtime, not import time). This is correct.

### R27-m1: `SparseResult` not exported from `__init__.py` (Minor)

`embeddings.py` exports `SparseResult` in its `__all__`, and it's used in `store.py` signatures (`hybrid_search(..., sparse_vector: SparseResult | None)`). However, `__init__.py` does not re-export `SparseResult`. Users who call `store.hybrid_search` directly need to import from `vaultspec_rag.embeddings` instead of the top-level package. This is inconsistent with the pattern where all public types (`CodeChunk`, `VaultDocument`, `SearchResult`, etc.) are re-exported from `__init__.py`.

__File:__ `__init__.py:17` (missing `SparseResult` in import)

## mcp_server.py (Second Pass)

### R27-PASS: R21-M6 and R21-M7 are fixed

- __R21-M6 (async tools block event loop):__ All search and reindex tools now use `asyncio.to_thread()` to run blocking GPU/Qdrant calls (lines 151, 183, 207, 261, 263, 290, 292). This is correct.
- __R21-M7 (get_comp not thread-safe):__ `get_comp()` now uses `_comp_lock` (threading.Lock) with proper double-checked locking (lines 54-58) and caches initialization failures in `_comp_error` (lines 60-63, 80-82). This is correct.

### R27-M1: `get_code_file` returns error strings instead of raising exceptions (Major)

Lines 236, 238, 242: When path traversal is detected, file is missing, or read fails, `get_code_file` returns an error string like `"Error: path '...' is outside the workspace."`. The MCP client receives this as a successful tool response with error text in the content field. A proper MCP error response would raise an exception so FastMCP returns an error-typed response. The client has no way to distinguish a successful file read from an error response without string-matching the content.

__File:__ `mcp_server.py:236, 238, 242`

### R27-M2: `get_vault_document` resource returns error string for missing doc (Major)

Line 315: `get_vault_document` returns `f"Document '{doc_id}' not found."` for a missing document. Like R27-M1, this is an error masquerading as successful content. The MCP resource protocol should raise a `ResourceError` or return an empty body with appropriate status.

__File:__ `mcp_server.py:315`

### R27-m2: `get_vault_document` resource has no test coverage (Minor)

The `vault://{doc_id}` resource (lines 305-316) is not tested in `test_mcp_server.py`. The test file checks `list_tools` and `list_prompts` but never calls `list_resources` or exercises the `get_vault_document` resource function.

__File:__ `test_mcp_server.py` (missing)

### R27-m3: `get_comp()` error message does not include root cause details (Minor)

Line 61-63: When a cached error exists, the re-raised message is `"RAG initialization previously failed"`. While the `from _comp_error` chain preserves the original exception, many MCP clients and log aggregators only display the top-level message. Including the original error's string (`f"RAG initialization previously failed: {_comp_error}"`) would make diagnosis easier without requiring full traceback inspection.

__File:__ `mcp_server.py:61-63`

### R27-m4: `get_code_file` does not validate file size before reading (Minor)

Line 240: `full_path.read_text(encoding="utf-8")` reads the entire file into memory with no size limit. A large binary file (e.g., a vendored `.wasm` or `.min.js`) could consume excessive memory. The indexer has `_MAX_FILE_SIZE = 10MB` but `get_code_file` has no equivalent guard.

__File:__ `mcp_server.py:240`

### R27-m5: `reindex_vault` response omits `files` field (Minor)

Lines 265-271: The `reindex_vault` `IndexResponse` does not set the `files` field (defaults to 0). `VaultIndexer.full_index` and `incremental_index` produce `IndexResult` with `files=0` (vault indexer counts documents, not files). This is technically correct but the `IndexResponse.files` field description says "Files processed" which is misleading for vault reindex. The field should either be omitted from vault responses or documented as vault-inapplicable.

__File:__ `mcp_server.py:265-271`

## Root conftest.py

### R27-M3: Root `conftest.py` imports constants at module level, coupling all pytest runs to vaultspec_rag (Major)

Line 9: `from vaultspec_rag.tests.constants import PROJECT_ROOT, TEST_PROJECT, TEST_VAULT`. This is a module-level import in the root conftest, meaning ANY pytest invocation from the repo root (even for non-RAG tests in other packages) will import `vaultspec_rag.tests.constants`. If `vaultspec_rag` is not installed (e.g., a developer working only on `vaultspec` core), this import fails and ALL tests crash.

The `# noqa: F401` comment indicates these are re-exports for backward compatibility, but the root conftest should not unconditionally depend on an optional subpackage.

__File:__ `conftest.py:9`

### R27-m6: Root conftest re-exports constants but has no fixtures (Minor)

The root conftest only does `from vaultspec_rag.tests.constants import ...` with `# noqa: F401`. These re-exports were likely needed when tests lived in the root `tests/` directory. Now that all tests are in `src/vaultspec_rag/tests/`, the root conftest serves no purpose other than backward compatibility with any remaining root-level test runners. If no root-level tests exist, this file could be emptied.

__File:__ `conftest.py`

## Previously-Flagged Issues: Status Update

| ID      | Issue                                               | Status                                                                                                                                                                                                                                                                                                             |
| ------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| R21-C1  | get_code_file symlink traversal                     | __Re-evaluated: NOT a vulnerability.__ Both `root_resolved` and `full_path` use `resolve()`, which follows symlinks. A symlink inside the workspace pointing outside resolves to a path outside `root_resolved`, so `is_relative_to` correctly rejects it. The test in `test_mcp_server.py:200-213` confirms this. |
| R21-M6  | MCP tools block event loop                          | __FIXED.__ All tools now use `asyncio.to_thread()`.                                                                                                                                                                                                                                                                |
| R21-M7  | get_comp() not thread-safe                          | __FIXED.__ Uses `threading.Lock` with double-checked locking.                                                                                                                                                                                                                                                      |
| R21-m11 | reindex_vault clean=True might not clear collection | __NOT AN ISSUE.__ `VaultIndexer.full_index()` explicitly deletes all existing docs before upserting (indexer.py:681-684).                                                                                                                                                                                          |

## Summary

| Severity | Count | IDs                    |
| -------- | ----- | ---------------------- |
| Major    | 3     | R27-M1, R27-M2, R27-M3 |
| Minor    | 6     | R27-m1 through R27-m6  |

__Key themes:__

1. __Error handling in MCP tools/resources__ (M1, M2): Errors returned as success strings instead of proper exceptions. MCP clients can't programmatically distinguish errors from content.
1. __Root conftest coupling__ (M3): Unconditional import of `vaultspec_rag` breaks non-RAG test runs when the package isn't installed.
1. __Previously-flagged fixes confirmed__ (R21-M6, R21-M7): Both are properly fixed with `asyncio.to_thread` and `threading.Lock`.
1. __R21-C1 downgraded__: Symlink traversal check is actually correct -- `resolve()` on both sides handles all scenarios. The test suite confirms this.
