---
tags:
  - '#exec'
  - '#stale-search-hits'
date: '2026-10-26'
modified: '2026-10-26'
body_schema: 'body-v2'
body_hash: 'sha256:06a96a330bad3357f2d1ca0d7a72eefbef1fa1f809b0ce3a240408150612905b'
related:
  - "[[2026-10-26-stale-search-hits-plan]]"
---

# `stale-search-hits` ledger

## Changes

- `S01` `A` `src/vaultspec_rag/_search_freshness.py`
- `S01` `A` `src/vaultspec_rag/_search_drift.py`
- `S01` `A` `src/vaultspec_rag/tests/test_search_hit_freshness.py`
- `S01` `A` `src/vaultspec_rag/tests/test_search_drift.py`
- `S01` `A` `.vault/reference/2026-10-26-stale-search-hits-reference.md`
- `S01` `A` `.vault/adr/2026-10-26-stale-search-hits-adr.md`
- `S01` `A` `.vault/plan/2026-10-26-stale-search-hits-plan.md`
- `S01` `A` `.vault/audit/2026-10-26-stale-search-hits-audit.md`
- `S01` `A` `.vault/index/stale-search-hits.index.md`
- `S01` `M` `src/vaultspec_rag/_job_admission.py`
- `S01` `M` `src/vaultspec_rag/jobs.py`
- `S01` `M` `src/vaultspec_rag/search/_models.py`
- `S01` `M` `src/vaultspec_rag/server/_models.py`
- `S01` `M` `src/vaultspec_rag/server/_runtime.py`
- `S01` `M` `src/vaultspec_rag/server/_routes_search.py`
- `S01` `M` `src/vaultspec_rag/server/_lifespan.py`
- `S01` `M` `src/vaultspec_rag/server/_main.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_publication_reads.py`
- `S01` `M` `src/vaultspec_rag/cli/_render.py`
- `S01` `M` `src/vaultspec_rag/cli/_search.py`
- `S01` `M` `src/vaultspec_rag/cli/_search_readiness_render.py`
- `S01` `M` `docs/search-and-index.md`
- `S01` `M` `.vault/adr/2026-09-07-explicit-reindex-authority-adr.md`
- `S01` `M` `.vault/adr/2026-09-08-search-readiness-contract-adr.md`
- `S01` `M` `.vault/adr/2026-09-08-incremental-publication-cost-adr.md`
- `S01` `verify:` `24 new CPU tests` -> `pass`
- `S01` `verify:` `349 existing CPU regressions` -> `pass`
- `S01` `verify:` `four fail-and-restore guard mutation sequences` -> `pass`
- `S01` `verify:` `package ruff lint and touched-file format` -> `pass`
- `S01` `verify:` `touched-file ty and strict basedpyright` -> `pass`
- `S01` `verify:` `scoped pylint and cognitive complexity` -> `pass`
- `S01` `verify:` `guide mdformat` -> `pass`
- `S01` `by:` `principal`
- `S01` `verify:` `scoped vault check all and schema` -> `pass`
- `S01` `verify:` `plan check` -> `pass`
- `S01` `verify:` `integrated review` -> `pass`
- `S08` `M` `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `S08` `M` `uv.lock`
- `S08` `verify:` `uv run --no-sync ruff check src tools dev conftest.py` -> `pass`
- `S08` `verify:` `uv run --no-sync ruff format --check src tools dev conftest.py` -> `pass`
- `S08` `verify:` `uv run --no-sync ty check src tools dev conftest.py` -> `pass`
- `S08` `verify:` `basedpyright changed pin constants in isolated identical source` -> `pass`
- `S08` `verify:` `canonical qdrant_pin_digests outgoing1.19 and new1.20 all12 each` -> `pass`
- `S08` `verify:` `integrated pin runtime/download/install/spawn tests117pass1platformskip` -> `pass`
- `S08` `by:` `principal`
- `S03` `M` `src/vaultspec_rag/server/_stdio_lifetime.py`
- `S03` `verify:` `integrated full Ruff lint0 format0 ty0 basedpyright0` -> `pass`
- `S03` `verify:` `identical isolated Windows stdio unit coverage37pass2POSIXskip` -> `pass`
- `S03` `verify:` `integrated configured complexity Xenon imports nesting pylint0` -> `pass`
- `S03` `by:` `principal`
- `S04` `M` `src/vaultspec_rag/tests/integration/test_search_result_shape.py`
- `S04` `verify:` `integrated full Ruff lint0 format0 ty0 basedpyright0` -> `pass`
- `S04` `verify:` `identical isolated result shape6pass and mutation fail restore pass` -> `pass`
- `S04` `verify:` `integrated configured complexity Xenon imports nesting pylint0` -> `pass`
- `S04` `by:` `principal`

## Notes

- `S08` User explicitly authorized including existing staged uv.lock update. Digest derivation executed no downloaded native binary. Full GPU baseline resource failures are unrelated and remain tracked in S02.
