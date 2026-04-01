---
tags:
  - "#audit"
  - "#gpu-rag-stack"
date: 2026-03-08
related: []
---

# Audit: --target Flag Propagation Through CLI Stack

**Date**: 2026-03-08
**Auditor**: codebase-researcher
**Scope**: CLI `--target` flag → workspace resolution → VaultStore → VaultIndexer → CodebaseIndexer → VaultSearcher → MCP server

## Summary

The `--target` flag propagation is **correct and consistent** across the entire stack. No bugs found. One minor observation about the MCP server path (documented below).

## Propagation Chain

### 1. CLI Entry (`cli.py:90-138`)

- `--target` is a `typer.Option` with `resolve_path=True` (line 101) — Typer resolves to absolute path before the callback runs.
- Passed to `resolve_workspace(target_override=target)` (line 134).
- Result stored in `CLIState.target = layout.target_dir` (line 72).
- `VAULTSPEC_ROOT` env var set to `str(self.target)` (line 74).

**Verdict**: CORRECT. Path is resolved, workspace validated.

### 2. Workspace Resolution (`workspace.py:188-237`)

- EXPLICIT mode (target_override provided): resolves, strips UNC prefix, sets `target_dir`, `vault_dir = target_dir / ".vault"`, `vaultspec_dir = target_dir / ".vaultspec"`.
- STANDALONE mode (no override): walks up for git root, uses repo root as target_dir.
- Validates that `vaultspec_dir` exists and `target_dir` exists.

**Verdict**: CORRECT. Clean separation of explicit vs auto-detected modes.

### 3. VaultStore (`store.py:115-143`)

- Constructor: `self.root_dir = Path(root_dir)`, `self.db_path = self.root_dir / cfg.qdrant_dir` (default `.qdrant`).
- Creates `db_path` directory, opens QdrantClient at that path.
- `root_dir` determines BOTH the source folder context AND the index storage location (`{root_dir}/.qdrant/`).

**Verdict**: CORRECT. Single root_dir controls both source and storage.

### 4. VaultIndexer (`indexer.py:612-632`)

- Stores `self.root_dir = root_dir`.
- Metadata path: `root_dir / cfg.qdrant_dir / cfg.index_metadata_file`.
- `full_index()`: calls `scan_vault(self.root_dir)` — scans `{root_dir}/.vault/` for docs.
- `prepare_document(path, self.root_dir)`: uses root_dir for relative path computation and doc type detection.

**Verdict**: CORRECT. root_dir is the source of truth for vault scanning.

### 5. CodebaseIndexer (`indexer.py:859-874`)

- Stores `self.root_dir = root_dir`.
- `_scan_codebase()`: walks `self.root_dir` with gitignore filtering.
- `_chunk_file()`: computes `path.relative_to(self.root_dir)` for relative paths stored in payloads.

**Verdict**: CORRECT. Same root_dir used for scanning and path relativization.

### 6. VaultSearcher (`search.py:169-186`)

- Stores `self.root_dir = root_dir`.
- Used only for graph building: `VaultGraph(self.root_dir)` and `rerank_with_graph(..., self.root_dir, ...)`.
- Does NOT use root_dir for search queries (those go through store).

**Verdict**: CORRECT. root_dir only used for graph context.

### 7. CLI Commands

All commands consistently extract `state.target` from `CLIState` and pass it to constructors:

| Command | Store | Indexer | Searcher |
|---------|-------|---------|----------|
| `index` (line 179) | `VaultStore(target)` | `VaultIndexer(target, ...)` | N/A |
| `search` (line 290) | `VaultStore(target)` | N/A | `VaultSearcher(target, ...)` |
| `status` (line 348) | `VaultStore(target)` | N/A | N/A |
| `benchmark` (line 475) | `VaultStore(target)` | N/A | `VaultSearcher(target, ...)` |

**Verdict**: CORRECT. All commands use the same `target` value.

### 8. MCP Server (`mcp_server.py:64-78`)

- Reads `VAULTSPEC_ROOT` env var, falls back to `Path.cwd()`.
- Passes `root_dir` to all component constructors consistently.
- The env var is set by `CLIState.__init__` (line 74), so `vaultspec-rag server mcp start` propagates the --target correctly IF invoked via the CLI.

**Observation**: The MCP server bypasses `resolve_workspace()` entirely — it reads the raw env var without workspace validation. This is acceptable because:

1. The CLI callback sets `VAULTSPEC_ROOT` after workspace validation.
2. BUT: the `main()` callback has an early return for `server` subcommand (line 129-130), meaning workspace resolution is SKIPPED for `server` commands.

**ISSUE FOUND**: When `vaultspec-rag --target /some/path server mcp start` is invoked:

- Line 129: `if ctx.invoked_subcommand in ("test", "quality", "server"): return` — this exits the callback BEFORE `resolve_workspace()` runs (line 133-135).
- Therefore `CLIState` is never created, `VAULTSPEC_ROOT` is never set from `--target`.
- The MCP server falls back to `Path.cwd()`, ignoring the `--target` flag entirely.

**Severity**: MEDIUM. The `--target` flag is silently ignored for `server mcp start`.

### 9. API Facade (`api.py:59-73`)

- `get_engine(root_dir)` resolves via `Path(root_dir).resolve()`.
- Singleton cache keyed on resolved path — correct.
- All public functions accept `root_dir` and pass to `get_engine()`.

**Verdict**: CORRECT.

### 10. Quality Command (`cli.py:584-685`)

- Hardcodes `test_project` path relative to package location, not from `--target`.
- This is intentional — quality command is a developer regression tool.
- Note: `VaultStore(test_project)` is created, then its Qdrant client is manually swapped to a temp dir (lines 612-618). This works but is fragile.

**Verdict**: CORRECT (by design, not target-dependent).

## Issues Found

### MEDIUM: --target silently ignored for `server mcp start`

**File**: `cli.py:129-130`
**Lines**: `if ctx.invoked_subcommand in ("test", "quality", "server"): return`

The early return for `"server"` skips workspace resolution, so `--target` has no effect on the MCP server. The MCP server falls back to `VAULTSPEC_ROOT` env var (if pre-set externally) or `Path.cwd()`.

**Impact**: Users running `vaultspec-rag --target /my/project server mcp start` will get results from cwd, not from `/my/project`.

**Fix options**:

1. Remove `"server"` from the early-return list and let workspace resolution run for server commands.
2. OR: Have the `mcp_start` command accept its own `--target` option.

## Conclusion

The propagation is correct for all non-server commands. The one bug is that `--target` is silently ignored when launching the MCP server via CLI.
