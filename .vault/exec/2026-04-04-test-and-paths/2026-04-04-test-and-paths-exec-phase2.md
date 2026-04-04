---
tags:
  - '#exec'
  - '#test-and-paths'
date: 2026-04-04
related:
  - '[[2026-04-04-test-and-paths-plan]]'
---

# `test-and-paths` phase-2 synthetic-corpus

Replaced the static 415-doc `test-project/` corpus with a synthetic
generator. Rewrote all test fixtures and conftest files. Migrated
`handle_quality()` to use synthetic corpus. Deleted `test-project/`.

- Created: `tests/corpus.py`
- Modified: `tests/constants.py`, `tests/conftest.py`,
  `tests/integration/conftest.py`, `tests/benchmarks/conftest.py`
- Modified: 8 test files (indexer_unit, search_integration,
  codebase_integration, indexer_integration, cli_integration,
  quality, performance, bench_rag)
- Modified: `cli.py` (`handle_quality()`)
- Deleted: `test-project/` (415 docs, git rm -rf)
- Modified: `.gitignore` (removed test-project rules)

## Description

- `corpus.py`: `build_synthetic_vault()` generates 6 doc types with
  unique needle keywords per doc. `build_multi_project_fixture()` for
  multi-project isolation. `CorpusManifest` dataclass carries docs,
  needles map, graph edges.
- `constants.py`: removed `TEST_PROJECT`, `TEST_VAULT`,
  `GPU_FAST_CORPUS_STEMS`, `QDRANT_SUFFIX_*`. Kept PROJECT_ROOT and
  port/timeout constants.
- All conftest files: replaced `_build_rag_components`/`_fast_index`
  with `_index_corpus()` + `build_synthetic_vault()` + `tmp_path`.
  No more qdrant suffix hacks.
- All test files: replaced TEST_PROJECT with fixture roots. Search
  assertions use needle keywords from manifest.
- `handle_quality()`: generates temp synthetic vault, indexes it, runs
  needle-based precision probes.

## Tests

- `ruff check src/` — zero violations
- Grep sweeps: zero hits for `.qdrant`, `test-project`, `TEST_PROJECT`,
  `TEST_VAULT`, `QDRANT_SUFFIX`, `GPU_FAST_CORPUS_STEMS`, bare
  `VAULTSPEC_` (without RAG\_)
- `test-project/` directory deleted from repo
