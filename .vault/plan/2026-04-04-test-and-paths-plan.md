---
tags:
  - '#plan'
  - '#test-and-paths'
date: 2026-04-04
modified: '2026-04-04'
related:
  - '[[2026-04-04-test-and-paths-adr]]'
  - '[[2026-04-04-test-and-paths-research]]'
---

# `test-and-paths` plan

Centralize all RAG data paths under `.vault/data/search-data/` and replace
the static `test-project/` corpus with a synthetic generator. Clean break —
no backwards compatibility. `.vault/data/` is the shared project data
namespace (owned by vaultspec-core); RAG owns only the `search-data/`
subtree.

## Mandates

These are non-negotiable constraints that apply to every step.

**M1 — Complete source audit.** Every `.py` file under `src/vaultspec_rag/`
MUST be read and audited for path declarations, hardcoded directories,
config lookups, and `Path.home()` usage. No file may be skipped. The
audit covers production code AND test code equally.

**M2 — Dual-control overrides.** Every path declaration MUST be overridable
via BOTH:

- **CLI argument** (e.g. `--data-dir`, `--qdrant-dir`, `--status-dir`)
- **Environment variable** (e.g. `VAULTSPEC_RAG_DATA_DIR`,
  `VAULTSPEC_RAG_QDRANT_DIR`, `VAULTSPEC_RAG_STATUS_DIR`)

CLI takes precedence over env var. Env var takes precedence over config
default. This mirrors the existing `--target` pattern. Document every
override in `.env.example`.

**M3 — Centralized definitions.** All path defaults MUST live in
`config.py` `_RAG_DEFAULTS`. No module may construct a path from a
hardcoded string. Every path is either:

- Read from config (`cfg.data_dir`, `cfg.qdrant_dir`, etc.), or
- Passed as a function/constructor parameter that traces back to config.

**M4 — Test fixture rewrite.** Every test fixture and conftest that
references `TEST_PROJECT`, `TEST_VAULT`, `QDRANT_SUFFIX_*`, or
constructs `.qdrant*` paths MUST be rewritten to use synthetic corpus +
`tmp_path` isolation + config overrides. No exceptions.

**M5 — Zero stale references.** After completion, `grep -r` for `.qdrant`,
`test-project`, `TEST_PROJECT`, `TEST_VAULT`, `QDRANT_SUFFIX`,
`GPU_FAST_CORPUS_STEMS` MUST return zero hits in `src/`.

**M6 — No bare `os.environ`.** No production module may call
`os.environ.get()` or `os.environ[...]` directly for configuration.
All env var wrangling MUST be centralized in `config.py` through:

- A `str` enum (`EnvVar` or similar) that defines every recognized env
  var name as a member (e.g. `EnvVar.RAG_ROOT = "VAULTSPEC_RAG_ROOT"`)
- A resolution method on `VaultSpecConfigWrapper` that reads the enum
  member from env, so callers use `cfg.root_dir` not
  `os.environ.get("VAULTSPEC_RAG_ROOT")`
- Every enum member MUST appear in `.env.example` with its default
  and description

Current violations in production code (6 files, all must be fixed):

- `cli.py:103,768` — sets `VAULTSPEC_ROOT`
- `cli.py:824` — reads `VAULTSPEC_RAG_STATUS_DIR`
- `cli.py:1309` — sets `HF_HUB_DOWNLOAD_TIMEOUT`
- `mcp_server.py:53` — reads `VAULTSPEC_ROOT`
- `mcp_server.py:81` — reads `HF_HOME`
- `logging_config.py:75` — reads `VAULTSPEC_RAG_LOG_LEVEL`
- `embeddings.py:199` — reads `HF_HOME`

Test code may use `os.environ` for fixture setup (setting/restoring
env vars around tests), but the string keys MUST reference the enum
members, not bare string literals.

**M7 — RAG namespace isolation.** `vaultspec-core` and `vaultspec-rag` are
complementary but separate projects. Every env var, config key, CLI arg,
log name, and user-facing string in the RAG codebase MUST use the
`VAULTSPEC_RAG_` prefix — never bare `VAULTSPEC_`. The existing
`VAULTSPEC_ROOT` env var (set in `cli.py:103`, read in
`mcp_server.py:53`, tested in `test_mcp_server.py`) MUST be renamed to
`VAULTSPEC_RAG_ROOT`. This prevents collision when both vaultspec-core
and vaultspec-rag are installed in the same environment.

## Full source audit — files requiring changes

Audit conducted against current codebase. Every file below MUST be
modified.

**Production code (7 files):**

- `config.py` — `_RAG_DEFAULTS` lines 29-41: `qdrant_dir=".qdrant"`,
  `index_metadata_file="index_meta.json"`. No `data_dir`. No
  `code_index_metadata_file`. No env var resolution.
- `store.py` — line 146: `self.db_path = self.root_dir / cfg.qdrant_dir`.
  Resolves directly from config, no `data_dir` indirection.
- `indexer.py` — line 791: vault meta
  `root_dir / cfg.qdrant_dir / cfg.index_metadata_file`. Line 1060: code
  meta `root_dir / cfg.qdrant_dir / "code_index_meta.json"` (hardcoded
  filename). Line 1097: prune list contains `".qdrant/"`.
- `cli.py` — line 103: sets `os.environ["VAULTSPEC_ROOT"]` (must rename
  to `VAULTSPEC_RAG_ROOT`). Line 768: same. Line 825:
  `Path.home() / ".vaultspec-rag"` for status dir (has env override but
  no CLI arg). Line 1507: hardcoded `test-project/` path in
  `handle_quality()`. Line 1077: service port default (already has env
  override, needs CLI arg audit).
- `logging_config.py` — line 75: `VAULTSPEC_RAG_LOG_LEVEL` env override
  (needs CLI arg).
- `mcp_server.py` — line 53: reads `os.environ.get("VAULTSPEC_ROOT")`
  (must rename to `VAULTSPEC_RAG_ROOT`). Lines 446-728: 7 docstrings
  reference `VAULTSPEC_ROOT` (must update).
- `api.py` — line 111: `Path(root_dir).resolve()` for engine cache key
  (takes root_dir param, traces to caller — OK).

**Test code (11 files):**

- `tests/constants.py` — `TEST_PROJECT`, `TEST_VAULT`,
  `GPU_FAST_CORPUS_STEMS`, `QDRANT_SUFFIX_FAST`, `QDRANT_SUFFIX_FULL`,
  `QDRANT_SUFFIX_UNIT`.
- `tests/conftest.py` — `_build_rag_components` with `.qdrant{suffix}`
  hack, `_fast_index`, `_vault_snapshot_reset` (git checkout
  test-project/).
- `tests/integration/conftest.py` — `QDRANT_SUFFIX_CODE`, TEST_PROJECT
  usage.
- `tests/benchmarks/conftest.py` — benchmark suffix hack.
- `tests/test_indexer_unit.py` — TEST_PROJECT, `.qdrant` references.
- `tests/integration/test_quality.py` — TEST_PROJECT.
- `tests/integration/test_search_integration.py` — TEST_PROJECT,
  `.qdrant`.
- `tests/integration/test_codebase_integration.py` — TEST_PROJECT,
  `.qdrant`.
- `tests/integration/test_indexer_integration.py` — TEST_PROJECT.
- `tests/integration/test_cli_integration.py` — TEST_PROJECT.
- `tests/integration/test_performance.py` — `.qdrant`.
- `tests/test_mcp_server.py` — 8 references to `VAULTSPEC_ROOT` env var
  (must rename to `VAULTSPEC_RAG_ROOT`).

## Dual-control override registry

Every path MUST have both columns filled before the step is complete.

| Setting          | Config key                 | Env var                         | CLI arg             | Default                           |
| ---------------- | -------------------------- | ------------------------------- | ------------------- | --------------------------------- |
| RAG data root    | `data_dir`                 | `VAULTSPEC_RAG_DATA_DIR`        | `--data-dir`        | `.vault/data/search-data`         |
| Qdrant storage   | `qdrant_dir`               | `VAULTSPEC_RAG_QDRANT_DIR`      | `--qdrant-dir`      | `{data_dir}/qdrant`               |
| Vault index meta | `index_metadata_file`      | `VAULTSPEC_RAG_INDEX_META`      | `--index-meta`      | `{data_dir}/index_meta.json`      |
| Code index meta  | `code_index_metadata_file` | `VAULTSPEC_RAG_CODE_INDEX_META` | `--code-index-meta` | `{data_dir}/code_index_meta.json` |
| Status directory | `status_dir`               | `VAULTSPEC_RAG_STATUS_DIR`      | `--status-dir`      | `~/.vaultspec-rag`                |
| Log file         | `log_file`                 | `VAULTSPEC_RAG_LOG_FILE`        | `--log-file`        | `{status_dir}/service.log`        |
| Service port     | `mcp_port`                 | `VAULTSPEC_RAG_PORT`            | `--port`            | `8766`                            |
| Log level        | `log_level`                | `VAULTSPEC_RAG_LOG_LEVEL`       | `--verbose/--debug` | `WARNING`                         |
| Project root     | (workspace)                | `VAULTSPEC_RAG_ROOT`            | `--target`          | git root or cwd                   |

Resolution order: CLI arg > env var > config default.

## Tasks

- Phase 1 — Centralize data paths (#33)

  1. Rewrite `config.py`:
     - Add `EnvVar(str, Enum)` defining every recognized env var as a
       member: `RAG_ROOT`, `DATA_DIR`, `QDRANT_DIR`, `INDEX_META`,
       `CODE_INDEX_META`, `STATUS_DIR`, `LOG_FILE`, `PORT`, `LOG_LEVEL`.
       Each member's value is the full env var string
       (e.g. `"VAULTSPEC_RAG_ROOT"`).
     - Update `_RAG_DEFAULTS`:
       - Add `data_dir = ".vault/data/search-data"`
       - Change `qdrant_dir` from `".qdrant"` to `"qdrant"` (relative to
         `data_dir`)
       - Add `code_index_metadata_file = "code_index_meta.json"`
       - Add `status_dir`, `log_file` keys
     - Update `VaultSpecConfigWrapper.__getattr__`: for each key, check
       the corresponding `EnvVar` member via `os.environ.get(EnvVar.X)`
       before falling back to `_RAG_DEFAULTS`. This is the ONLY place
       `os.environ` is called for config resolution.
     - Remove the old `".qdrant"` default entirely
  1. Add CLI args to `cli.py` `main()` callback: `--data-dir`,
     `--qdrant-dir`, `--index-meta`, `--code-index-meta`, `--status-dir`,
     `--log-file`. Wire each into `CLIState` so they flow into config
     overrides. Follow the existing `--target` pattern.
  1. Update `store.py` `VaultStore.__init__`:
     - Resolve `db_path` as `root_dir / cfg.data_dir / cfg.qdrant_dir`
  1. Update `indexer.py`:
     - `VaultIndexer.__init__` line 791: meta path becomes
       `root_dir / cfg.data_dir / cfg.index_metadata_file`
     - `CodebaseIndexer.__init__` line 1060: meta path becomes
       `root_dir / cfg.data_dir / cfg.code_index_metadata_file`
     - Line 1097: update `os.walk` prune list
  1. Update `cli.py` service helpers:
     - `_status_dir()`: read from `cfg.status_dir` (which already checks
       env var via config). Remove standalone `os.environ.get`.
     - `_log_file()`: read from `cfg.log_file`.
  1. Create/update `.env.example`: document every `VAULTSPEC_RAG_*` env
     var with its default and description.
  1. Eliminate all bare `os.environ` calls in production code:
     - `cli.py:103,768`: replace `os.environ["VAULTSPEC_ROOT"] = ...`
       with `os.environ[EnvVar.RAG_ROOT] = ...` (or route through
       config setter)
     - `cli.py:824`: remove `os.environ.get("VAULTSPEC_RAG_STATUS_DIR")`
       — `cfg.status_dir` already resolves it via `__getattr__`
     - `cli.py:1309`: `HF_HUB_DOWNLOAD_TIMEOUT` is a third-party env
       var — wrap in an `EnvVar` member or a named constant
     - `mcp_server.py:53`: replace with `cfg` lookup or `EnvVar.RAG_ROOT`
     - `mcp_server.py:81`, `embeddings.py:199`: `HF_HOME` is third-party
       — add as `EnvVar.HF_HOME` member so the string is defined once
     - `logging_config.py:75`: replace with `cfg.log_level` or
       `EnvVar.LOG_LEVEL`
     - In test code: replace all bare string env var names with
       `EnvVar.X.value` references
  1. Rename `VAULTSPEC_ROOT` → `VAULTSPEC_RAG_ROOT` everywhere:
     - `cli.py` lines 103, 768: `os.environ["VAULTSPEC_RAG_ROOT"]`
     - `mcp_server.py` line 53: `os.environ.get("VAULTSPEC_RAG_ROOT")`
     - `mcp_server.py` lines 446-728: update all docstrings
     - `tests/test_mcp_server.py`: all 8 env var references
  1. Add `.vault/data/search-data/` to `.gitignore`.
  1. Verify: `ruff check src/` passes. Grep confirms no remaining
     `.qdrant` hardcoded defaults and no bare `VAULTSPEC_ROOT` in
     production code.

- Phase 2 — Synthetic test corpus (#32)

  1. Create `src/vaultspec_rag/tests/corpus.py`:
     - `build_synthetic_vault(root, *, n_docs, include_malformed, graph_density, seed)` returns `CorpusManifest`
     - `build_multi_project_fixture(base, *, n_projects)` returns
       `list[CorpusManifest]`
     - `CorpusManifest` dataclass: `root`, `docs`, `needles` map,
       `graph_edges`
     - Each doc gets a unique needle keyword for deterministic precision@K
     - Cover all 6 doc types, configurable graph density, optional
       malformed docs
  1. Rewrite `tests/constants.py`:
     - Remove: `TEST_PROJECT`, `TEST_VAULT`, `GPU_FAST_CORPUS_STEMS`,
       `QDRANT_SUFFIX_FAST`, `QDRANT_SUFFIX_FULL`, `QDRANT_SUFFIX_UNIT`
     - Keep: `PROJECT_ROOT`, `LIB_SRC`, `SCRIPTS`, port/timeout/delay
       constants
  1. Rewrite `tests/conftest.py`:
     - Replace `_build_rag_components` and `_fast_index` with fixtures
       backed by `build_synthetic_vault()` + `tmp_path_factory`
     - Remove `_vault_snapshot_reset` (no test-project/ to reset)
     - Each fixture gets its own `tmp_path`-based data dir via config
       override — no suffix hacks
  1. Rewrite `tests/integration/conftest.py`: same pattern — synthetic
     corpus, `tmp_path` isolation, config overrides. Remove
     `QDRANT_SUFFIX_CODE`.
  1. Rewrite `tests/benchmarks/conftest.py`: same pattern.
  1. Migrate every test file (8 files, one by one):
     - `test_indexer_unit.py`
     - `integration/test_search_integration.py`
     - `integration/test_codebase_integration.py`
     - `integration/test_indexer_integration.py`
     - `integration/test_cli_integration.py`
     - `integration/test_quality.py`
     - `integration/test_performance.py`
     - `benchmarks/bench_rag.py`
     - For each: replace `TEST_PROJECT` with synthetic fixture root,
       update search assertions to use needle keywords, verify no
       `.qdrant` or `test-project` references remain.
  1. Migrate `cli.py` `handle_quality()`:
     - Replace `test-project/` with `build_synthetic_vault()` in a temp
       directory
     - Update `_QUALITY_PROBES` to use needle keywords
  1. Delete `test-project/` directory from repo.
  1. Final verification (see below).

## Parallelization

Phase 1 steps 1-7 are sequential (each builds on prior path changes).
Phase 2 step 1 (corpus.py) can start alongside phase 1.
Phase 2 steps 2-8 are sequential. Step 9 (delete test-project/) is the
final gate.

## Verification

**Automated (must all pass):**

- `uv run pytest src/vaultspec_rag/tests/ -x` — all tests pass
- `uv run ruff check src/` — zero violations

**Grep sweeps (must all return zero hits in `src/`):**

- `grep -r '\.qdrant' src/` — zero (old qdrant path gone)
- `grep -r 'test-project' src/` — zero
- `grep -r 'TEST_PROJECT' src/` — zero
- `grep -r 'TEST_VAULT' src/` — zero
- `grep -r 'QDRANT_SUFFIX' src/` — zero
- `grep -r 'GPU_FAST_CORPUS_STEMS' src/` — zero
- `grep -rP 'VAULTSPEC_(?!RAG_)' src/` — zero (no bare VAULTSPEC\_ without RAG\_ prefix)
- `grep -rP 'os\.environ.*(get|set|pop|\[).*"[A-Z_]+"' src/vaultspec_rag/*.py` — zero in production code (no bare string env var names outside `config.py`)

**Override registry verification:**

For each row in the dual-control table: confirm that the setting can be
controlled via CLI arg, env var, and config default. This means writing
at least one test per setting that exercises the override chain
(CLI > env > default).

**Structural checks:**

- `.vault/data/search-data/` in `.gitignore`
- `.env.example` documents every `VAULTSPEC_RAG_*` variable
- `test-project/` directory no longer exists
- Needle-based search assertions confirm precision@K is deterministic
