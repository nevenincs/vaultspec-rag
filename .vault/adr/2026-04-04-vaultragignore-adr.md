---
# REQUIRED TAGS (minimum 2): one directory tag + one feature tag
# DIRECTORY TAGS: #adr #audit #exec #plan #reference #research
# Directory tag (hardcoded - DO NOT CHANGE - based on .vault/adr/ location)
# Feature tag (replace vaultragignore with your feature name, e.g., #editor-demo)
# Additional tags may be appended below the required pair
tags:
  - '#adr'
  - '#vaultragignore'
# ISO date format (e.g., 2026-02-06)
date: '2026-04-04'
# Related documents as quoted wiki-links
# (e.g., "[[2026-02-04-feature-research]]")
related:
  - '[[2026-04-04-vaultragignore-research]]'
---

# `vaultragignore` ADR: design decisions | (**status:** `proposed`)

## Problem Statement

`CodebaseIndexer` indexes all git-tracked source files that pass `.gitignore` filtering,
but users have no mechanism to exclude files that are tracked by git yet irrelevant to
semantic search (generated code, vendored deps, large fixtures, build outputs).

Issue: wgergely/vaultspec-rag#31.
See research in `2026-04-04-vaultragignore-research`.

## Considerations

- `pathspec>=0.12` is already a project dependency — use `pathspec.GitIgnoreSpec`
- 4 production call sites create `CodebaseIndexer` — new params must be backward-compatible
- `.vaultragignore` must augment, never override `.gitignore` exclusions
- Watcher already re-reads `_scan_codebase()` on every code change — no special monitoring needed
- The filename `.vaultragignore` is a convention (like `.gitignore`) — no config key needed

## Constraints

- GPU always available (RTX 4080) — integration tests must use real GPU
- No mocks/patches in tests — use `CodebaseIndexer.__new__()` pattern for unit tests
- `just ci` (ruff + pytest) must pass

## Decisions

### D1: Two-spec OR architecture

**Decision:** Build `.gitignore` and `.vaultragignore` as independent `pathspec.GitIgnoreSpec`
instances. A file is excluded if **either** spec matches.

**Rationale:** A single merged spec would allow `.vaultragignore` negation patterns (`!foo`)
to override `.gitignore` exclusions. Two-spec OR guarantees `.gitignore` is inviolable while
preserving full gitignore syntax within `.vaultragignore` (including internal negation).

**Consequences:** Slightly more complex matching (two `match_file()` calls per path), but
negligible perf impact since `os.walk` I/O dominates.

### D2: Root-only `.vaultragignore`

**Decision:** Read a single `.vaultragignore` file from the project root directory only.
Not recursive like `.gitignore`.

**Rationale:** Recursive `.vaultragignore` adds complexity with minimal benefit — codebase
exclusions are typically project-wide patterns (e.g., `*.generated.py`, `vendor/`, `fixtures/`).

### D3: Silent on missing file

**Decision:** Missing `.vaultragignore` is silently ignored. No error, no warning, no log.

**Rationale:** Most projects won't have this file. Logging would be noise.

### D4: `extra_excludes` constructor parameter

**Decision:** Add `extra_excludes: list[str] | None = None` keyword arg to
`CodebaseIndexer.__init__`. Patterns merge into the vaultragignore spec.

**Rationale:** Threads CLI `--exclude` patterns without changing the 4 existing call sites
(they all default to `None`). Service/watcher/MCP don't need ad-hoc exclusions.

### D5: Public `scan_files()` method

**Decision:** Expose `scan_files() -> list[pathlib.Path]` as a public method wrapping
`_scan_codebase()`. Used by CLI `--dry-run`.

**Rationale:** Dry-run needs file listing without GPU/Qdrant initialization. Constructing
`CodebaseIndexer(root, model=None, store=None)` for dry-run is acceptable since
`scan_files()` touches neither field.

### D6: `--dry-run` scope is codebase only

**Decision:** `--dry-run` only lists codebase files, not vault documents.

**Rationale:** `.vaultragignore` only applies to `CodebaseIndexer`. Vault documents are
managed by `vaultspec-core`'s `scan_vault()` with its own filtering.

### D7: Extract `_build_gitignore_spec()` and `_build_vaultragignore_spec()`

**Decision:** Refactor `_scan_codebase()` to extract pattern loading into two private
methods, keeping the walk loop clean.

**Rationale:** Testability — unit tests can exercise spec building without running `os.walk`.

### D8: No config key, no watcher changes

**Decision:** No `config.py` changes. No watcher `.vaultragignore` monitoring needed.

**Rationale:** The filename `.vaultragignore` is a convention — configuring it adds
indirection for zero benefit. The watcher triggers `incremental_index()` on code changes,
which calls `_scan_codebase()`, which re-reads `.vaultragignore` every time. Edits to
`.vaultragignore` take effect on next index run naturally. No MCP tool for listing patterns
is needed in v1 — `--dry-run` serves that debugging purpose from the CLI.

### D9: `--dry-run` short-circuits before `--port` MCP delegation

**Decision:** The `--dry-run` early return must come before the `--port` MCP fast-path
block in `handle_index`.

**Rationale:** Dry-run is a local file listing — it should never delegate to an MCP server.
Similarly, `--exclude` is ephemeral CLI state and does not flow through the MCP reindex API.
If `--exclude` is passed with `--port` (without `--dry-run`), log a warning that `--exclude`
is ignored when using MCP server delegation.

## Implementation

See plan in `2026-04-04-vaultragignore-plan`.

### Phase 1: Core (`indexer.py`)

1. Add `extra_excludes` kwarg to `__init__`, store as `self._extra_excludes`
1. Extract `_build_gitignore_spec()` from current `_scan_codebase()` pattern loading
1. Add `_build_vaultragignore_spec()` — reads `.vaultragignore` + merges `_extra_excludes`
1. Update `_scan_codebase()` walk loop to check both specs (OR)
1. Add public `scan_files()` method

### Phase 2: CLI (`cli.py`)

1. Add `--dry-run` flag and `--exclude` repeatable option to `handle_index`
1. Dry-run early return before `--port` block — construct lightweight indexer, call `scan_files()`
1. Non-dry-run path: pass `extra_excludes` to `CodebaseIndexer`
1. Warn if `--exclude` used with `--port` (without `--dry-run`)

### Phase 3: Tests

1. Unit tests (no GPU): spec building, negation isolation, missing file, extra_excludes
1. Integration test (real GPU): full index with `.vaultragignore`, verify exclusions
1. CLI test: `--dry-run` output, `--exclude` patterns

## Consequences

- 4 existing `CodebaseIndexer` call sites unchanged (new kwarg defaults to `None`)
- No config, watcher, or MCP changes — feature is entirely contained in indexer + CLI
- Two `match_file()` calls per path in `_scan_codebase()` — negligible overhead
- `scan_files()` becomes the first public method on `CodebaseIndexer` that doesn't require GPU

## Files modified

- `src/vaultspec_rag/indexer.py` — core implementation
- `src/vaultspec_rag/cli.py` — CLI options
- `src/vaultspec_rag/tests/test_indexer_unit.py` — unit tests
- `src/vaultspec_rag/tests/integration/test_codebase_integration.py` — integration test
