---
tags:
  - '#exec'
  - '#test-and-paths'
date: 2026-04-04
modified: '2026-06-30'
related:
  - '[[2026-04-04-test-and-paths-plan]]'
---

# `test-and-paths` phase-1 data-paths

Centralized all RAG data paths under `.vault/data/search-data/`, added
`EnvVar` enum, dual-control overrides (CLI + env), and eliminated bare
`os.environ` calls from production code.

- Modified: `config.py`, `store.py`, `indexer.py`, `cli.py`,
  `mcp_server.py`, `embeddings.py`, `logging_config.py`
- Modified (tests): `test_mcp_server.py`, `test_cli.py`
- Modified: `.gitignore`, `.env.example`

## Description

- Added `EnvVar(StrEnum)` to `config.py` with 11 members covering all
  recognized env vars (RAG-prefixed + third-party HF vars)
- Updated `_RAG_DEFAULTS`: `data_dir=".vault/data/search-data"`,
  `qdrant_dir="qdrant"` (relative), added `code_index_metadata_file`,
  `status_dir`, `log_file`, `mcp_port`, `log_level`
- `VaultSpecConfigWrapper.__getattr__` now resolves: CLI override (base
  config) > env var (via `_ENV_OVERRIDE_MAP`) > default
- Added 6 CLI args to `cli.py` `main()`: `--data-dir`, `--qdrant-dir`,
  `--index-meta`, `--code-index-meta`, `--status-dir`, `--log-file`
- `store.py` path: `root_dir / cfg.data_dir / cfg.qdrant_dir`
- `indexer.py` meta paths: `root_dir / cfg.data_dir / cfg.{meta_file}`
- Renamed `VAULTSPEC_ROOT` to `VAULTSPEC_RAG_ROOT` in `cli.py`,
  `mcp_server.py`, and test files
- All bare `os.environ` calls in production code replaced with
  `EnvVar` references or `cfg` lookups
- `.env.example` documents all 9 `VAULTSPEC_RAG_*` variables

## Tests

- `ruff check` passes on all modified files (0 violations)
- Grep confirms zero bare `"VAULTSPEC_ROOT"` string literals in `src/`
- Test file `.qdrant` references are expected — cleaned in Phase 2
