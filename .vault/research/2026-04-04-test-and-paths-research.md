---
tags:
  - '#research'
  - '#test-and-paths'
date: 2026-04-04
modified: '2026-04-04'
related:
  - '[[2026-04-02-service-graph-adr]]'
  - '[[2026-04-02-service-graph-code-review-audit]]'
---

# `test-and-paths` research: centralized data paths + synthetic test corpus

Two coupled changes tracked in #33 (data paths) and #32 (test corpus).
#33 must land first because it changes where Qdrant/index metadata lives,
which affects every test fixture. This research covers both issues.

## Findings

### Part 1: Centralized data paths (#33)

**Current state — path sprawl:**

- `config.py` `_RAG_DEFAULTS`: `qdrant_dir=".qdrant"`, `index_metadata_file="index_meta.json"`
- `store.py:146`: `self.db_path = self.root_dir / cfg.qdrant_dir` — Qdrant data at `{root}/.qdrant/`
- `indexer.py:791`: vault meta at `{root}/.qdrant/index_meta.json`
- `indexer.py:1060`: code meta at `{root}/.qdrant/code_index_meta.json`
- `cli.py:815-845`: service status/logs at `~/.vaultspec-rag/` (global, already has `VAULTSPEC_RAG_STATUS_DIR` env override)
- `conftest.py:102`: tests build `{root}/.qdrant{suffix}/` directories with ad-hoc suffix isolation

**Problems:**

- `.qdrant/` at project root is a top-level dotdir that pollutes the workspace
- No `.gitignore` entry for `.qdrant/` (only `.lance/` is listed)
- Index metadata files are buried inside the qdrant dir — logically separate concerns (metadata != vector DB storage)
- No centralized path constant — each module resolves its own path from config
- Test fixtures manually construct qdrant paths with suffix hacks

**Proposed migration:**

- Default `qdrant_dir` moves from `.qdrant` to `.vault/data/qdrant`
- Default `index_metadata_file` moves to `.vault/data/index_meta.json`
- Code index meta moves to `.vault/data/code_index_meta.json`
- All three paths derive from a single `data_dir` concept: `{root}/.vault/data/`
- `_RAG_DEFAULTS` gains `data_dir=".vault/data"` — the parent for all persistent RAG data
- `qdrant_dir` becomes relative to `data_dir` (just `"qdrant"`)
- `index_metadata_file` and `code_index_metadata_file` become relative to `data_dir`
- Add `.vault/data/` to `.gitignore`

**Env var overrides** (already partially in place for status dir):

| Env var                    | Default                      | Overrides                            |
| -------------------------- | ---------------------------- | ------------------------------------ |
| `VAULTSPEC_RAG_DATA_DIR`   | `.vault/data`                | `data_dir` — parent for all RAG data |
| `VAULTSPEC_RAG_QDRANT_DIR` | `{data_dir}/qdrant`          | absolute or relative to root         |
| `VAULTSPEC_RAG_INDEX_META` | `{data_dir}/index_meta.json` | vault index meta path                |
| `VAULTSPEC_RAG_STATUS_DIR` | `~/.vaultspec-rag`           | already exists in `cli.py`           |

**Legacy detection:**

- `VaultStore.__init__` checks if `{root}/.qdrant/` exists when the new path is empty
- If found, logs a warning: "Legacy .qdrant/ detected — run `vaultspec-rag doctor` to migrate"
- `doctor` command gains a migration step: moves `.qdrant/` contents to `.vault/data/qdrant/`

**Impact on tests:**

- `conftest.py:_build_rag_components` simplifies: instead of suffix hacks on `.qdrant{suffix}`, each test fixture uses `tmp_path`-based isolation with `VAULTSPEC_RAG_DATA_DIR` env override or config override
- `constants.py` drops `QDRANT_SUFFIX_*` constants
- Test isolation becomes: `tmp_path / "data"` per fixture, no suffix arithmetic

**Impact on `config.py`:**

- `VaultSpecConfigWrapper.__getattr__` already chains base → defaults. No structural change needed.
- Add 3 new keys to `_RAG_DEFAULTS`: `data_dir`, `code_index_metadata_file`
- `qdrant_dir` default changes from `".qdrant"` to resolving `data_dir + "/qdrant"`
- Consider a `resolve_data_path(root: Path) -> Path` helper that checks env → config → default

**Risk assessment:** LOW — path changes are internal, no public API surface. Tests will need updating but the suffix hack removal is a net simplification.

### Part 2: Synthetic test corpus (#32)

**Current state — static test-project/:**

- `test-project/.vault/` contains 415 markdown docs across all doc_types (adr, plan, exec, research, reference, audit, stories)
- Git-tracked; `.gitignore` preserves `.vault/` and `README.md` only
- `constants.py:27`: `TEST_PROJECT = PROJECT_ROOT / "test-project"`
- `GPU_FAST_CORPUS_STEMS`: 13 hand-picked stems covering all 5 doc_types
- `conftest.py:_fast_index`: indexes only the 13-stem subset for speed
- `handle_quality()` in `cli.py` uses `test-project/` directly for quality probes
- `_QUALITY_PROBES`: 8 known-answer queries with labels (security audit, pipeline executor, etc.)

**Problems:**

- 415 docs is large; full-corpus indexing is slow (~GPU minutes)
- Docs are static — can't parameterize for edge cases (malformed frontmatter, broken tags, orphans, cycles)
- No multi-project fixture for testing service registry's per-project isolation
- Precision@K assertions are fragile — content drifts as docs are edited
- `test-project/` is a top-level directory that adds noise to the repo

**Proposed design — `src/vaultspec_rag/tests/corpus.py`:**

```python
def build_synthetic_vault(
    root: Path,
    *,
    n_docs: int = 20,
    include_malformed: bool = False,
    graph_density: float = 0.3,  # fraction of docs with wiki-links
    seed: int = 42,
) -> CorpusManifest:
    """Generate a .vault/ with predictable, searchable content."""
```

**Document generation strategy:**

- Each doc gets a unique "needle" keyword (e.g., `NEEDLE_ADR_001`) for precision@K
- Doc types: adr, plan, research, exec, reference, audit (6 types × n_docs/6 each)
- Features: 3-4 distinct feature tags, distributed evenly
- Frontmatter: valid YAML with tags, date, related fields
- Body: 2-3 paragraphs of topically distinct content per doc type
- Graph links: `related:` fields link docs within features (chain A→B→C)
- When `include_malformed=True`: add docs with missing frontmatter, broken tags, empty body, duplicate IDs
- When `graph_density > 0`: cross-feature links, cycles (A→B→A)

**CorpusManifest return type:**

```python
@dataclass
class CorpusManifest:
    root: Path
    docs: list[GeneratedDoc]
    needles: dict[str, str]  # needle_keyword -> doc_id
    graph_edges: list[tuple[str, str]]  # (from_id, to_id)
```

**Multi-project fixture:**

```python
def build_multi_project_fixture(
    base: Path,
    *,
    n_projects: int = 2,
) -> list[CorpusManifest]:
    """Two project roots with distinct, non-overlapping corpora."""
```

**Conftest fixtures:**

- `synthetic_vault(tmp_path_factory)` — session-scoped, 20 docs, standard
- `multi_project_roots(tmp_path_factory)` — session-scoped, 2 projects × 10 docs
- `malformed_vault(tmp_path)` — function-scoped, includes malformed docs

**Migration path for test-project/:**

- Tests migrate to synthetic fixtures
- `handle_quality()` in CLI either:
  - (a) generates a temp synthetic corpus at runtime (preferred — self-contained), or
  - (b) keeps `test-project/` as a CLI-only quality corpus, not used by unit/integration tests
- Option (b) is simpler for now. Quality probes need stable content to be meaningful — a generated corpus with known needles works better.
- Either way, `test-project/` references are removed from all test files.
- `test-project/` directory can be deleted from the repo once `handle_quality()` migrates.

**Known-answer queries:**

Each generated doc has a unique needle. Quality assertions become:

```python
def test_search_finds_needle(rag_components, synthetic_vault):
    results = searcher.search_vault("NEEDLE_ADR_001", top_k=5)
    assert any(r["id"] == synthetic_vault.needles["NEEDLE_ADR_001"] for r in results)
```

This is deterministic — no content drift, no fragile stem matching.

**Impact on test counts:**

- Current: 220+ unit tests, many using the fast 13-stem subset
- After: same tests, but backed by synthetic corpus
- New tests possible: malformed doc handling, multi-project isolation, graph cycle detection, orphan docs

**Risk assessment:** MEDIUM — touching all test fixtures is high-blast-radius, but each change is mechanical (swap `TEST_PROJECT` → `synthetic_vault.root`). The synthetic corpus makes tests faster and more predictable.

### Ordering and dependencies

1. **#33 first**: migrate `_RAG_DEFAULTS` paths, add `.vault/data/` to `.gitignore`, add env overrides, legacy detection
1. **#32 second**: create `corpus.py`, add conftest fixtures, migrate tests away from `test-project/`
1. **Final**: update `handle_quality()` to use synthetic corpus, remove `test-project/`

### Open questions for ADR

- Should `data_dir` be absolute or always relative to `root_dir`? (Recommendation: relative by default, env override can be absolute)
- Should `handle_quality()` keep `test-project/` or fully migrate to synthetic? (Recommendation: fully migrate — `test-project/` is 415 static docs of debt)
- Should `_RAG_DEFAULTS` resolve paths eagerly (at config creation) or lazily (at access)? (Recommendation: lazily — config is created before root_dir is known in some flows)
