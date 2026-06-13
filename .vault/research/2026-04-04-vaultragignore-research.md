---
tags:
  - '#research'
  - '#vaultragignore'
date: '2026-04-04'
modified: '2026-04-04'
related:
  - '[[2026-04-04-vaultragignore-adr]]'
  - '[[2026-04-04-vaultragignore-plan]]'
---

# `vaultragignore` research: codebase indexer exclusion support

## Summary

Investigated how `CodebaseIndexer._scan_codebase()` handles file exclusions, identified
the integration point for `.vaultragignore`, and explored design options for pattern
isolation, CLI threading, and dry-run support.

## Findings

## Problem statement

The `CodebaseIndexer` has hardcoded exclusions (`.venv/`, `.git/`, `node_modules/`,
`__pycache__/`, `.qdrant/`) and respects `.gitignore`, but there is no way to exclude
**git-tracked** files from indexing. Generated code, vendored dependencies, large
fixtures, build artifacts checked into git, etc. get indexed unnecessarily — wasting
GPU compute, inflating the vector store, and degrading search relevance.

**Issue:** wgergely/vaultspec-rag#31

## Current architecture

### `CodebaseIndexer._scan_codebase()` (indexer.py:1097–1166)

The scan pipeline already uses `pathspec.GitIgnoreSpec`:

1. Builds `patterns: list[str]` starting with 5 hardcoded directory exclusions
1. Recursively collects all `.gitignore` files, prefixing patterns by relative subdirectory
1. Creates a single `pathspec.GitIgnoreSpec.from_lines(patterns)`
1. Walks with `os.walk(topdown=True)`, pruning dirs in-place + matching files

Key observations:

- `pathspec>=0.12` is already a project dependency
- Pattern loading and matching is localized to `_scan_codebase()` — no other method touches it
- Both `full_index()` and `incremental_index()` call `_scan_codebase()` as their first step

### Constructor signature

```python
CodebaseIndexer.__init__(root_dir, model, store, *, gpu_lock=None)
```

### Call sites (4 production + tests)

| Location         | Call                                                           | Notes                             |
| ---------------- | -------------------------------------------------------------- | --------------------------------- |
| `cli.py:371`     | `CodebaseIndexer(target, emb_model, store)`                    | No gpu_lock                       |
| `service.py:256` | `CodebaseIndexer(root, model, store, gpu_lock=self._gpu_lock)` | Service registry                  |
| `api.py:75`      | `CodebaseIndexer(root_dir, self.model, self.store)`            | Public facade                     |
| `watcher.py`     | Receives pre-built instance                                    | Calls `.incremental_index()` only |
| `mcp_server.py`  | Gets from `ProjectSlot.code_indexer`                           | Via service registry              |

### Config system (`config.py`)

`VaultSpecConfigWrapper` holds 12 RAG defaults (qdrant_dir, models, batch sizes, etc.).
No ignore-pattern config exists yet.

## Design exploration

### Q1: Where to load `.vaultragignore` patterns?

**Inside `_scan_codebase()`** — directly alongside the `.gitignore` loading. This is the
simplest integration point, keeps pattern logic co-located, and ensures `.vaultragignore`
changes take effect on next index without restart.

### Q2: Single spec vs two separate specs?

**Decision: Two separate specs (OR logic).**

If all patterns go into one `GitIgnoreSpec`, a negation `!foo` in `.vaultragignore` would
un-ignore `foo` from `.gitignore`. The requirement is "augments, never overrides."

With two specs:

- `gitignore_spec` = hardcoded + all `.gitignore` patterns
- `vaultragignore_spec` = `.vaultragignore` + CLI `--exclude` patterns
- A file is excluded if **either** spec matches

This preserves full gitignore syntax within `.vaultragignore` (including internal negation
like `*.log` + `!important.log`) while guaranteeing `.gitignore` exclusions are inviolable.

### Q3: How to thread CLI `--exclude` patterns?

Add `extra_excludes: list[str] | None = None` keyword argument to `CodebaseIndexer.__init__`.
Store on `self._extra_excludes`. Merge into the vaultragignore spec in `_scan_codebase()`.

This only needs to flow through the CLI path — service/watcher/MCP don't need ad-hoc
exclusions (they use the `.vaultragignore` file).

### Q4: How to implement `--dry-run`?

Expose `scan_files() -> list[pathlib.Path]` as a public method (thin wrapper over
`_scan_codebase()`). For dry-run, construct `CodebaseIndexer` with `model=None, store=None`
(type-ignored) since `scan_files()` touches neither. This avoids GPU model loading and
Qdrant initialization.

### Q5: Scope of `--dry-run`?

**Codebase only.** Vault docs come from `vaultspec-core`'s `scan_vault()` which has its own
filtering. `.vaultragignore` only applies to `CodebaseIndexer`.

### Q6: Multiple `.vaultragignore` files?

**Root-only.** Unlike `.gitignore` which is scanned recursively, only one `.vaultragignore`
at project root. Keeps semantics simple. Patterns are relative to root (same as `.gitignore`).

### Q7: Missing `.vaultragignore`?

Silently ignored — no error, no warning. Just use the gitignore spec alone.

## Proposed refactoring

Extract pattern loading from `_scan_codebase()` into two private methods:

1. `_build_gitignore_spec() -> pathspec.GitIgnoreSpec` — hardcoded + `.gitignore` patterns
1. `_build_vaultragignore_spec() -> pathspec.GitIgnoreSpec | None` — `.vaultragignore` + `extra_excludes`

Then `_scan_codebase()` checks files against both specs (short-circuit OR).

## Files to modify

| File                           | Change                                                                              |
| ------------------------------ | ----------------------------------------------------------------------------------- |
| `indexer.py`                   | Add `extra_excludes` param, extract spec builders, add `scan_files()` public method |
| `cli.py`                       | Add `--dry-run` and `--exclude` options to `handle_index`                           |
| `test_indexer_unit.py`         | Unit tests for pattern loading, spec separation, negation isolation                 |
| `test_codebase_integration.py` | Integration test: index with `.vaultragignore`, verify exclusions                   |

**No changes needed to:** `service.py`, `api.py`, `mcp_server.py`, `watcher.py` — they
all read `.vaultragignore` automatically through the indexer's scan pipeline.

## Resolved questions

1. **Config key for filename?** No — `.vaultragignore` is a convention like `.gitignore`.
   Configuring it adds indirection for zero benefit.
1. **Watcher monitoring?** Not needed — the watcher triggers `incremental_index()` on code
   changes, which calls `_scan_codebase()`, which re-reads `.vaultragignore` every time.
   Edits take effect on next index run naturally.
1. **MCP tool for listing patterns?** Not needed — `--dry-run` serves this purpose from CLI.
   MCP consumers can inspect the `.vaultragignore` file directly.
