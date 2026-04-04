---
tags:
  - '#adr'
  - '#test-and-paths'
date: 2026-04-04
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
