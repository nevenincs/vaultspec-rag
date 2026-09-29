---
tags:
  - '#adr'
  - '#test-and-paths'
date: '2026-04-04'
modified: '2026-09-26'
body_hash: 'sha256:3973e2e85d04c531d3ccb465debd3c8a506a795917963517b236cb6f567d5ecf'
related:
  - '[[2026-04-04-test-and-paths-research]]'
  - '[[2026-04-02-service-graph-adr]]'
---

# `test-and-paths` adr: centralized data paths + synthetic test corpus | (**status:** `accepted`)

## Problem Statement

RAG data paths (Qdrant storage, index metadata) are scattered across modules
with inconsistent resolution. `.qdrant/` at project root pollutes the
workspace. The test suite depends on a static 415-doc `test-project/` corpus
that cannot be parameterized for edge cases, is slow to index fully, and
couples assertions to hand-maintained content.

## Considerations

- `config.py` `_RAG_DEFAULTS` already centralizes RAG config with proxy
  access via `VaultSpecConfigWrapper`
- `cli.py` already has `VAULTSPEC_RAG_STATUS_DIR` env override for service
  status — establishes the env var naming convention
- `VaultStore.__init__` resolves `root_dir / cfg.qdrant_dir` — single point
  of change for storage path
- Both indexers derive `_meta_path` from `cfg.qdrant_dir` — currently
  coupled to qdrant directory
- Test fixtures use `qdrant_suffix` hacks to isolate fast/full/unit fixtures
- `handle_quality()` hardcodes `test-project/` for CLI quality probes

## Constraints

- **Clean break — no backwards compatibility.** No legacy `.qdrant/`
  detection, no migration hints, no deprecation warnings, no shims.
- **CRITICAL: `.vault/data/` is NOT the RAG data root.** `.vault/data/` is
  the shared project data namespace owned by vaultspec-core. RAG search
  artifacts live under `.vault/data/search-data/`. This separation ensures
  other tools and plugins can use `.vault/data/` without colliding with RAG
  storage.
- Paths must be lazily resolved (config may be created before root_dir is
  known)
- Env overrides must support both absolute and relative paths
- Test corpus must produce deterministic, needle-based content for
  precision@K
- No mocks/patches — real GPU, real Qdrant for all RAG tests
- **No bare `os.environ` in production code.** All env var names MUST be
  defined as members of a `str` enum in `config.py`. All env var reads
  MUST flow through `VaultSpecConfigWrapper.__getattr__`. No production
  module may call `os.environ.get/set/pop` with string literals. Test
  code may use `os.environ` for fixture setup but MUST reference enum
  members for key names. Every enum member MUST appear in `.env.example`.
- **RAG namespace isolation.** `vaultspec-core` and `vaultspec-rag` are
  complementary but separate projects sharing the same `VAULTSPEC_`
  namespace. Every env var, config key, and user-facing string in the RAG
  codebase MUST use the `VAULTSPEC_RAG_` prefix — never bare `VAULTSPEC_`.
  The existing `VAULTSPEC_ROOT` env var MUST be renamed to
  `VAULTSPEC_RAG_ROOT` to prevent collision when both packages are
  installed side-by-side.

**Amendment note, 2026-09-26**: The enum lives at `config/_types.py:51` (`class EnvVar(StrEnum)`), not in a file named `config.py`; settings keys resolve through `VaultSpecConfigWrapper.__getattr__` (`config/_settings.py:1188`) as stated, but the "no bare `os.environ`" rule holds only for settings keys — call-time switches read `os.environ` directly through `EnvVar` members by design, e.g. `search/_typesafe_transport.py:71,106`, `server/_stdio_lifetime.py:57,97` (`STDIO_WATCHDOG_ENV = EnvVar.STDIO_WATCHDOG.value`), and `config/_types.py:287` (`hf_cache_only`). Current exceptions to both this rule and the `VAULTSPEC_RAG_` prefix rule, standing as code to correct rather than as precedent: string-literal `UV_CACHE_DIR`/`UV_TOOL_DIR` reads (`cli/_gpu_errors.py:76,81`), a string-literal `PYTORCH_ENABLE_MPS_FALLBACK` read (`_gpu.py:77`), the undeclared bare-`VAULTSPEC_` `VAULTSPEC_JUNCTION_PATH`/`VAULTSPEC_JUNCTION_TARGET` subprocess-env keys (`commands/_mcp_topology.py:879-880`), the module-local literal `VAULTSPEC_PREPROCESS_INVOCATION` (`indexer/_preprocess_schema.py:45,74`), and `memory_probe.py:98` (`ENV_VAR = "VAULTSPEC_RAG_MEMORY_PROBE"`), which is prefix-correct but read as a bare literal instead of an `EnvVar` member.

**Amendment note, 2026-09-26**: No record states the value vocabulary or invalid-value policy the code applies today; recorded here as the code's current, unamended behavior. `_env_values.py:25,31` defines the one boolean vocabulary - `TRUE_TOKENS = {"1", "true", "yes", "on"}`, `FALSE_TOKENS = {"0", "false", "no", "off", ""}`; `config/_settings.py:959-1012` (`_validate_settings`) rejects invalid values at construction and reports every unusable setting together; `config/_settings.py:925-936` treats a blank string override for a string-typed setting as absent, falling back to the module default; fail-safe readers - the stdio watchdog (`server/_stdio_lifetime.py:100-104`) and other `parse_bool`-based switches that must not block startup - warn and fall through to the safe state instead of raising. The shared resolution order, env-file rule, boolean vocabulary and install-flag contract these facts bear on are proposed for vaultspec-core's `2026-09-26-env-parity-adr`.

## Implementation

**Phase 1 — Centralize data paths (#33):**

- Add `data_dir = ".vault/data/search-data"` to `_RAG_DEFAULTS`
- Change `qdrant_dir` default from `".qdrant"` to `"qdrant"` (relative to
  `data_dir`)
- Add `code_index_metadata_file = "code_index_meta.json"` to defaults
- `index_metadata_file` and `code_index_metadata_file` resolve relative to
  `data_dir`
- `VaultStore.__init__` resolves: `root_dir / data_dir / qdrant_dir`
- Indexer meta paths resolve: `root_dir / data_dir / {meta_file}`
- Add env overrides: `VAULTSPEC_RAG_DATA_DIR`, `VAULTSPEC_RAG_QDRANT_DIR`,
  `VAULTSPEC_RAG_INDEX_META`
- Add `.vault/data/search-data/` to `.gitignore`
- Delete all references to the old `.qdrant` default

**Phase 2 — Synthetic test corpus (#32):**

- Create `src/vaultspec_rag/tests/corpus.py`:
  - `build_synthetic_vault(root, *, n_docs, include_malformed, graph_density, seed)` returns `CorpusManifest`
  - `build_multi_project_fixture(base, *, n_projects)` returns `list[CorpusManifest]`
- Each doc gets a unique needle keyword (e.g. `NEEDLE_ADR_001`) for
  deterministic precision@K
- 6 doc types (adr, plan, research, exec, reference, audit), 3-4 feature
  tags, configurable graph density
- `CorpusManifest` dataclass: `root`, `docs`, `needles` map, `graph_edges`
- `include_malformed=True` adds: missing frontmatter, broken tags, empty
  body, orphans, cycles
- Session-scoped fixtures: `synthetic_vault`, `multi_project_roots`;
  function-scoped: `malformed_vault`
- Migrate all test files from `TEST_PROJECT` to synthetic fixtures
- `handle_quality()` migrates to synthetic corpus (generates temp dir at
  runtime)
- Delete `test-project/` from repo entirely
- Drop `QDRANT_SUFFIX_*` constants — fixture isolation via `tmp_path` +
  config overrides

## Rationale

- `.vault/data/search-data/` is the natural home for RAG artifacts — keeps project root
  clean, aligns with `.vault/` as the project data namespace
- Clean break avoids dead code paths for a layout nobody should use going
  forward
- Lazy resolution avoids breaking flows where config is instantiated early
- Synthetic corpus eliminates 415-doc static fixture maintenance, enables
  edge-case parameterization, and makes precision@K deterministic via needle
  keywords
- Phase 1 before phase 2 because path changes affect every fixture — migrate
  fixtures once paths are stable

## Consequences

- Existing `.qdrant/` directories are abandoned. Users must re-index.
- Test fixture rewrite touches ~10 files; each change is mechanical
- `test-project/` deletion is permanent — quality probes replaced by
  generated needles
- `VAULTSPEC_RAG_*` env var convention established for future config

## Considered options

- **Selected:** the implementation recorded above because it satisfies the stated rationale and constraints.
- **Not selected:** approaches that conflict with those recorded constraints.
