# Continuous Audit Log — 2026-03-08

## [08:37] Audit: --target flag propagation

**Status**: PASS with 1 MEDIUM issue

See full report: `docs/audit/2026-03-08-target-flag-propagation.md`

### MEDIUM findings

- **--target silently ignored for `server mcp start`** — `cli.py:129-130`: early return for `"server"` subcommand skips `resolve_workspace()`, so `CLIState` is never created and `VAULTSPEC_ROOT` env var is never set from `--target`. MCP server falls back to `Path.cwd()`.

### PASS

- CLI resolves path via Typer `resolve_path=True` — correct
- `resolve_workspace()` handles explicit vs auto-detected modes — correct
- VaultStore uses root_dir for both source scanning and storage — correct
- All CLI commands (index, search, status, benchmark) pass `state.target` consistently
- VaultIndexer/CodebaseIndexer/VaultSearcher all use the same root_dir
- API facade resolves via `Path.resolve()` with singleton caching — correct

## [08:55] Audit: Test corpus size — why 415 files?

**Status**: PASS with 2 MAJOR observations

### Analysis

The test corpus at `test-project/.vault/` contains 415 `.md` files in the working tree:

- 265 exec (execution summaries)
- 58 reference
- 35 research
- 29 adr
- 19 plan
- 7 stories
- 2 audit

**Committed to git**: 394 `.md` files + 75 `.jsonl` log files = 469 total files.
**Untracked (not committed)**: 21 additional `.md` files, which include ALL 13 `GPU_FAST_CORPUS_STEMS` files.

The `.jsonl` log files (75 files) are NOT scanned by `scan_vault()` because it only yields `*.md` files — correct.

### MAJOR findings

- **GPU_FAST_CORPUS_STEMS files are untracked** — The 13 stems used by the fast test fixture (`conftest.py:32-53`) are all untracked files (e.g., `2026-01-10-pipeline-execution-model.md`, `2026-01-18-nexus-security-audit.md`). They exist in the working tree but are NOT committed. This means:
  1. A fresh clone would NOT have these files
  2. The fast test fixture (`rag_components`) would index 0 documents on a clean checkout
  3. `_vault_snapshot_reset` runs `git checkout -- test-project/.vault/` which would DELETE these files, breaking subsequent test runs in the same worktree
  - **File**: `tests/constants.py:32-53`, `tests/conftest.py:181-197`
  - **Impact**: Tests fail on clean clone. CI would fail.

- **`_vault_snapshot_reset` is destructive to untracked files** — The session-scoped autouse fixture runs `git checkout -- test-project/.vault/` on teardown (`conftest.py:187-188`). This restores tracked files but also removes any untracked additions. Since the 21 test-critical files are untracked, running the test suite once would delete them from the working tree.
  - **File**: `tests/conftest.py:181-197`
  - **Impact**: After one test run, the GPU_FAST_CORPUS_STEMS files may be deleted. However, `git checkout -- <path>` does NOT delete untracked files — it only restores tracked files. So this specific concern is mitigated. The real risk is that these files simply don't exist on a clean clone.

### MINOR findings

- **Corpus is large for a test fixture** — 415 docs is substantial. The full-corpus fixture indexes all 415 docs with real GPU inference, which is slow. The fast fixture (13 docs) mitigates this well.
- **75 .jsonl log files are committed** — These are vaultspec agent execution logs from 2026-02-19. They serve no testing purpose and add ~75 files to the repo. Should be gitignored.

### PASS

- `scan_vault()` correctly scans only `*.md` under `{root}/.vault/`, skipping `.obsidian`
- `_fast_index()` filters by stem correctly
- Test isolation via qdrant suffixes (`.qdrant-fast/`, `.qdrant-full/`) — correct
- `_vault_snapshot_reset` runs as session-scoped autouse — correct scope

## [09:05] Audit: Model loading lifecycle

**Status**: FAIL — 2 MAJOR issues

### Where EmbeddingModel is instantiated

| Location | Scope | Caching | Notes |
|----------|-------|---------|-------|
| `cli.py:198` (index cmd) | Per CLI invocation | None | Fresh model every `vaultspec-rag index` |
| `cli.py:294` (search cmd) | Per CLI invocation | None | Fresh model every `vaultspec-rag search` |
| `cli.py:486` (benchmark cmd) | Per CLI invocation | None | Fresh model every `vaultspec-rag benchmark` |
| `cli.py:608` (quality cmd) | Per CLI invocation | None | Fresh model every `vaultspec-rag quality` |
| `api.py:46` (_Engine.**init**) | Singleton via get_engine() | Yes — `_engine` global + `threading.Lock` | Reused across calls with same root_dir |
| `mcp_server.py:74` (get_comp) | Singleton via `_comp` global | Yes — `threading.Lock`, cached forever | Created once on first MCP tool call |
| `tests/conftest.py:101` | session-scoped fixture | Yes — pytest session scope | One model per test session |

### MAJOR findings

- **CLI model loading is a 5-15s overhead per invocation** — Every CLI command (index, search, benchmark, quality) creates a fresh `EmbeddingModel()`, loading Qwen3-Embedding-0.6B (~1.2GB) + SPLADE v3 into GPU VRAM from scratch. For a `search` command that should feel interactive, 5-15 seconds of model loading before the actual search executes is a severe UX problem. The search itself takes <100ms, but the total wall time is dominated by model init.
  - **File**: `cli.py:198,294,486,608`
  - **Impact**: Unusable latency for interactive CLI usage. Users will avoid CLI search.
  - **Fix options**: (1) Resident model server/daemon that keeps models loaded; (2) CLI connects to MCP server for search instead of loading models itself; (3) Model memory-mapping or faster loading strategies.

- **Multiple EmbeddingModel instances in test session** — The `rag_components` (fast) and `rag_components_full` fixtures each create a separate `EmbeddingModel()` instance (`conftest.py:101`). If both fixtures are used in the same session, two copies of the models are loaded onto GPU, consuming ~2-3GB VRAM unnecessarily.
  - **File**: `tests/conftest.py:80-128`, lines 131-167
  - **Impact**: Wasted GPU memory. Could cause OOM on smaller GPUs.
  - **Fix**: Extract a session-scoped `embedding_model` fixture shared by both.

### MINOR findings

- **EmbeddingModel has no `close()`/`__del__` method** — No explicit resource cleanup. The underlying SentenceTransformer and SparseEncoder are released by Python GC. Fine for CLI one-shots, but for long-lived processes a manual release mechanism would be useful.

### PASS

- API facade: singleton via `get_engine()` with `threading.Lock` — correct, model loaded once
- MCP server: singleton via `get_comp()` with `threading.Lock` + error caching — correct, model loaded once on first tool call
- Constructor correctly checks CUDA availability before loading models
- OOM retry logic with halving batch size — correct
- Sparse model uses `encode_document()` / `encode_query()` asymmetric API — correct
- Dense model uses `prompt_name="query"` for queries, omits for documents — correct
- flash_attention_2 probe before loading prevents double model load — correct

## [09:15] Audit: GPU test isolation and parallel execution config

**Status**: PASS with 2 MEDIUM concerns

### pytest configuration (`pyproject.toml:79-97`)

- `asyncio_mode = "auto"` — correct for async tests
- `timeout = 300` with `timeout_func_only = true` — 5 min per test, timeout applies only to function body (not setup/teardown)
- `testpaths = ["src/vaultspec_rag/tests"]` — correct, uses new test location
- 6 markers defined: unit, integration, performance, quality, robustness, timeout
- No `addopts` — no default flags like `-n auto` or `--forked`
- **No pytest-xdist** — not in dependencies, not in any config, not referenced anywhere in the codebase

### Parallel execution analysis

**pytest-xdist is NOT installed or configured.** All tests run sequentially in a single process. This means:

- No risk of concurrent GPU access from parallel test workers
- No risk of Qdrant lock contention from parallel processes
- But also: no parallelism benefit for CPU-bound unit tests

### Fixture isolation

5 separate `rag_components*` fixture definitions, each calling `_build_rag_components()` which creates a new `EmbeddingModel()`:

| Fixture | File | Scope | Qdrant suffix | Model instance |
|---------|------|-------|---------------|---------------|
| `rag_components` | `tests/conftest.py:132` | session | `-fast` | Own |
| `rag_components_full` | `tests/conftest.py:151` | session | `-full` | Own |
| `rag_components` | `tests/integration/conftest.py:17` | session | `-fast-unit` | Own |
| `rag_components_with_code` | `tests/integration/conftest.py:36` | session | `-fast-code` | Own |
| `rag_components_mixed` | `tests/integration/test_search_integration.py:139` | session | `-mixed` | Own |

**Key observation**: The `rag_components` fixture is defined TWICE — once in `tests/conftest.py` and once in `tests/integration/conftest.py`. The integration one overrides the parent for integration tests (using suffix `-fast-unit` instead of `-fast`). This is intentional pytest fixture scoping.

However, if a test session runs BOTH unit and integration tests, up to 5 `EmbeddingModel()` instances could be created. In practice, pytest session-scoped fixtures share the same session, so all 5 could coexist in GPU memory simultaneously.

### MEDIUM findings

- **Up to 5 EmbeddingModel instances in one test session** — Each `_build_rag_components()` call creates its own model. With Qwen3 (~600MB) + SPLADE (~300MB) per instance, 5 instances = ~4.5GB GPU memory for models alone, plus Qdrant storage. Could OOM on GPUs with <8GB VRAM.
  - **Fix**: Create a single session-scoped `embedding_model` fixture and pass it to `_build_rag_components()` instead of instantiating inside.

- **No guard against future xdist adoption** — If someone adds `pytest-xdist` later, GPU tests would run in parallel workers that each try to load models and access Qdrant simultaneously. No `xdist_group` markers or `pytest_collection_modifyitems` hook exists to prevent this.
  - **Fix**: Add a `pytest_collection_modifyitems` hook or `xdist_group` markers preemptively, or document the no-xdist constraint.

### PASS

- Sequential execution ensures no GPU contention — correct by default
- Qdrant isolation via unique suffixes per fixture — correct, no cross-fixture interference
- Session scope for all GPU fixtures — correct, avoids repeated model loading within a fixture's scope
- `timeout = 300` is generous enough for GPU tests — correct
- `timeout_func_only = true` avoids timing out during fixture setup (model loading) — correct and important

## [09:25] Audit: CLI <-> MCP shape consistency

**Status**: PASS with 3 MINOR mismatches

### Feature matrix

| Feature | CLI Command | MCP Tool | Match? |
|---------|-------------|----------|--------|
| Search vault | `search --type vault` | `search_vault()` | Partial |
| Search code | `search --type code` | `search_codebase()` | Partial |
| Search all | N/A | `search_all()` | **CLI missing** |
| Index vault | `index --type vault` | `reindex_vault()` | Partial |
| Index code | `index --type code` | `reindex_codebase()` | Partial |
| Index all | `index --type all` | N/A | **MCP missing** |
| Status | `status` | `get_index_status()` | Partial |
| Get file | N/A | `get_code_file()` | **CLI missing** |
| Benchmark | `benchmark` | N/A | CLI only |
| Quality | `quality` | N/A | CLI only |
| Test | `test` | N/A | CLI only |

### Parameter comparison

**Search:**

- CLI `search`: `query` (positional), `--type` (vault|code), `--max-results` (default 5)
- MCP `search_vault`: `query`, `top_k` (default 5) — no type param needed
- MCP `search_codebase`: `query`, `top_k`, `language`, `node_type`, `function_name`, `class_name`
- MCP `search_all`: `query`, `top_k`
- **Mismatch**: CLI search has no `language`/`node_type`/`function_name`/`class_name` filters for code search. MCP has them. CLI uses `--max-results`, MCP uses `top_k`.

**Index:**

- CLI `index`: `--type` (vault|code|all), `--model` (override), `--clean`
- MCP `reindex_vault`: `clean` (bool) — no model override
- MCP `reindex_codebase`: `clean` (bool) — no model override
- **Mismatch**: CLI has `--model` override, MCP does not. CLI has `--type all` (combined), MCP requires two separate calls. MCP uses "clean" semantics differently — `clean=False` means incremental, matching CLI's default behavior.

**Status:**

- CLI `status`: GPU info + storage path + vault count + code count + target dir
- MCP `get_index_status`: vault_count + code_count + storage_path only
- **Mismatch**: MCP status is a subset — no GPU info, no target directory.

**Return shapes:**

- CLI search returns a Rich table (visual only)
- MCP search returns `SearchResponse` Pydantic model with `results: list[SearchResultItem]` + `summary: str`
- Both use the same underlying `SearchResult` dataclass from `search.py` — consistent

### MINOR findings

- **CLI has no `search_all` equivalent** — MCP provides `search_all()` for combined vault+code search, but CLI `search` only supports `--type vault` or `--type code`, not both. Users must run two commands.
  - **File**: `cli.py:270-324` vs `mcp_server.py:205-223`

- **CLI search missing code filters** — MCP `search_codebase` accepts `language`, `node_type`, `function_name`, `class_name` filters, but CLI `search --type code` has no equivalents.
  - **File**: `cli.py:270-324` vs `mcp_server.py:161-202`

- **MCP status is a subset of CLI status** — CLI `status` shows GPU name, VRAM, target dir; MCP `get_index_status` returns only counts and storage path.
  - **File**: `cli.py:327-363` vs `mcp_server.py:226-238`

### PASS

- Search result schema is consistent — both use `SearchResult` from `search.py`
- MCP `reindex_vault/reindex_codebase` correctly maps to `VaultIndexer.full_index(clean=True)` / `incremental_index()`
- MCP `get_code_file` has proper path traversal protection (`is_relative_to` check) — correct
- MCP `_clamp_top_k` prevents abuse (1-100) — CLI has no such guard but accepts int from argparse
- MCP tools use `anyio.to_thread.run_sync()` for all sync operations — correct for async MCP server
- `analyze_feature` prompt is MCP-only, which is fine (not a CLI concern)

## [09:35] Audit: Auto-setup / health check — cold start behavior

**Status**: PASS — clean cold start behavior, 1 MINOR UX gap

### Cold start trace

**Scenario**: Fresh workspace with no `.qdrant/` directory and no indexed data.

| Component | Cold start behavior | Creates on demand? | Error on empty? |
|-----------|--------------------|--------------------|-----------------|
| `VaultStore.__init__` | Creates `.qdrant/` dir via `mkdir(parents=True)` | Yes | No |
| `ensure_table()` | Creates `vault_docs` collection if missing | Yes | No |
| `ensure_code_table()` | Creates `codebase_docs` collection if missing | Yes | No |
| `hybrid_search()` on empty collection | Calls `ensure_table()`, then `query_points` returns `[]` | N/A | No — returns empty list |
| `count()` on empty collection | Calls `ensure_table()`, returns 0 | N/A | No |
| MCP `search_vault` on empty | Returns `SearchResponse(results=[], summary="Found 0 ...")` | N/A | No |
| MCP `get_index_status` on empty | Returns `IndexStatus(vault_count=0, code_count=0, ...)` | N/A | No |
| MCP `reindex_vault` on empty `.vault/` | `scan_vault()` returns 0 paths, `full_index()` returns `IndexResult(total=0)` | N/A | No |
| CLI `search` on empty | Prints "No results found" message | N/A | No |
| CLI `index` on empty `.vault/` | Indexes 0 docs, shows summary table with all zeros | N/A | No |

**GPU initialization failure**:

- `EmbeddingModel.__init__` raises `RuntimeError` if no CUDA — CLI catches with `_handle_gpu_error()` (user-friendly message + exit 1)
- MCP `get_comp()` caches the error in `_comp_error` and re-raises on subsequent calls — prevents retry of expensive GPU init

**Missing `.vault/` directory**:

- `scan_vault()` checks `docs_dir.exists()` and returns immediately if not — logs debug message, yields nothing
- No error, no crash — just 0 documents indexed

### MINOR findings

- **No "index first" hint on empty search** — When MCP `search_vault` returns 0 results because nothing is indexed (not because the query is bad), the summary says "Found 0 relevant documents" with no indication that the user should run indexing first. CLI `search` similarly shows "No results found" without suggesting `vaultspec-rag index`.
  - **Impact**: Users may not realize they need to index before searching.
  - **Fix**: Check `store.count()` before search and include a hint in the response if count is 0.

### PASS

- All collections created on demand — no manual setup required
- `.qdrant/` directory created automatically by `VaultStore.__init__`
- Empty collection searches return clean empty results
- GPU failure cached in MCP to prevent retry — correct
- CLI GPU error handling is user-friendly with actionable messages
- Missing `.vault/` handled gracefully by `scan_vault()`

## [09:50] Audit: Coder implementations review — Task #16 (GPU semaphore) and Task #18 (xdist hook)

### Task #16: GPU semaphore in mcp_server.py

**Status**: PASS with 1 MINOR observation

**Implementation review** (`mcp_server.py:46,190,237,261,334,365`):

- `_gpu_sem = asyncio.Semaphore(1)` at module level — correct, single permit = mutex
- Applied to: `search_vault`, `search_codebase`, `search_all`, `reindex_vault`, `reindex_codebase`
- NOT applied to: `get_index_status`, `get_code_file`, `get_vault_document` — correct, these are read-only and don't use GPU
- Pattern: `async with _gpu_sem: result = await anyio.to_thread.run_sync(_run)` — correct, acquires semaphore before dispatching to thread

**Correctness analysis**:

- The semaphore is `asyncio.Semaphore`, which is bound to the event loop. Since MCP runs on a single event loop, all tool calls contend for the same semaphore — correct serialization.
- The `anyio.to_thread.run_sync(_run)` runs the actual GPU work in a thread pool, but since the semaphore is held, no two GPU operations can overlap — correct.
- `get_comp()` initialization is protected by `threading.Lock`, not the semaphore. This is fine because init only happens once and is already thread-safe.

**Watcher integration** (`mcp_server.py:90-115`):

- `_ensure_watcher()` is called AFTER the semaphore is released (after the `async with` block) — correct, the watcher will acquire `_gpu_sem` independently when it needs to re-index.
- The watcher (`watcher.py:129,155`) also acquires `_gpu_sem` before re-indexing — correct, shared serialization with MCP tools.
- Watcher has its own cooldown timer (30s default) — correct debounce layer.

**MINOR observation**:

- `get_index_status` calls `store.count()` and `store.count_code()` which are Qdrant reads. If a re-index is in progress (holding the semaphore), these reads could see partial state. This is acceptable for a status endpoint — eventual consistency is fine.

### Task #18: xdist_group hook in conftest.py

**Status**: PASS — clean implementation

**Implementation review** (`conftest.py:1-25` at repo root):

```python
_GPU_MARKERS = frozenset({"integration", "quality", "performance", "robustness"})

def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    gpu_group = pytest.mark.xdist_group("gpu")
    for item in items:
        item_markers = {m.name for m in item.iter_markers()}
        if item_markers & _GPU_MARKERS:
            item.add_marker(gpu_group)
```

**Correctness analysis**:

- Covers all 4 GPU markers: `integration`, `quality`, `performance`, `robustness` — correct, `unit` is intentionally excluded (no GPU needed)
- Groups all GPU tests into `xdist_group("gpu")` — when xdist is installed, all GPU tests run in the same worker
- No-op when xdist is not installed — `pytest.mark.xdist_group` is just a marker, doesn't error
- Uses `frozenset` intersection for O(1) lookup — efficient
- Placed in root `conftest.py` — correct, applies to all test files

**Edge cases verified**:

- A test with both `@pytest.mark.unit` and `@pytest.mark.integration` would get the xdist_group marker (correct — if it's integration, it needs GPU)
- A test with no markers would NOT get the xdist_group marker (correct — unmarked tests don't need GPU)

### PASS (both implementations)

- GPU semaphore correctly serializes all GPU-bound MCP operations
- Watcher shares the same semaphore for re-index GPU access
- xdist_group hook covers all GPU markers, is a no-op without xdist
- Both implementations are minimal and correct
