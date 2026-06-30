---
tags:
  - '#exec'
  - '#test-and-paths'
date: 2026-04-04
modified: '2026-06-30'
related:
  - '[[2026-04-04-test-and-paths-plan]]'
  - '[[2026-04-04-test-and-paths-adr]]'
  - '[[2026-04-04-test-and-paths-exec-phase1]]'
  - '[[2026-04-04-test-and-paths-exec-phase2]]'
---

# `test-and-paths` execution summary

Both phases executed successfully. All mandates (M1-M7) satisfied.

- Modified: 14 production/test source files
- Created: `synthetic.py`, `tests/corpus.py` (re-export)
- Modified: `.gitignore`, `.env.example`
- Deleted: `test-project/` (415 docs)

## Description

**Phase 1 — Centralized data paths (#33):**

- `EnvVar(StrEnum)` in `config.py` with 11 members
- `_RAG_DEFAULTS` updated: `data_dir=".vault/data/search-data"`,
  `qdrant_dir="qdrant"` (relative), new keys for code_index_meta,
  status_dir, log_file, mcp_port, log_level
- `_ENV_OVERRIDE_MAP` + `__getattr__` env resolution
- 6 CLI args added to `main()` callback
- `store.py`, `indexer.py` path resolution via `cfg.data_dir`
- `VAULTSPEC_ROOT` → `VAULTSPEC_RAG_ROOT`
- All bare `os.environ` calls eliminated from production code

**Phase 2 — Synthetic test corpus (#32):**

- `synthetic.py`: `build_synthetic_vault()` with 6 doc types, needle
  keywords, graph density, malformed option
- All conftest files rewritten: `tmp_path` isolation, no suffix hacks
- 8 test files migrated to synthetic fixtures
- `handle_quality()` uses synthetic corpus + needle probes
- `test-project/` deleted from repo

**Code review findings fixed:**

- Phase 1: bool coercion order, bare envvar string, log_level default
  alignment, dynamic prune list
- Phase 2: date bug (stale loop variable), production→test import
  coupling (moved to `synthetic.py`), search_vault vs search

## Tests

- `ruff check src/` — zero violations
- Grep sweeps: zero stale references in `src/`
- `test-project/` deleted, `.gitignore` cleaned
- `.env.example` documents all 9 `VAULTSPEC_RAG_*` variables
- Dual-control override registry complete (9 settings × 3 columns)
