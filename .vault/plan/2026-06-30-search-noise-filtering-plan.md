---
tags:
  - '#plan'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
tier: L2
related:
  - '[[2026-06-30-search-noise-filtering-adr]]'
  - '[[2026-06-30-search-noise-filtering-research]]'
---

# `search-noise-filtering` plan

### Phase `P01` - Foundation: shared domain classifier and index-time domain

Establish one worker-safe domain classifier and persist a per-chunk domain at index time, and stop indexing transient worktree clones.

- [x] `P01.S01` - Create a worker-safe pure classify_domain(path) returning prod/tests/docs/locale/generated/vendored/worktree, supersede the prefer classifier to consume it, with unit tests; `src/vaultspec_rag/_domain.py`.
- [x] `P01.S02` - Write a per-chunk domain payload at code index time, add domain to the code KEYWORD index set ensuring the index idempotently on existing collections, and exclude nested worktree clone dirs from the scan; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P02` - Query-time mechanisms: domain filters, pushdown, backfill, profile

Add domain-aware exclude/only filters with pushdown and no-silent-depletion backfill, the demote-or-hide policy pass, the persistent noise profile, and the dedup default flip.

- [x] `P02.S03` - Extend the code filter builder for domain must/must_not pushdown driving exclude-domain and only-domain; `src/vaultspec_rag/store.py`.
- [x] `P02.S04` - Add the post-rerank apply_domain_policy demote-or-hide pass, resolve exclude/only/include-domain, add the backfill loop with a filtered envelope note, and flip dedup-locales default on, with unit tests; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P02.S05` - Add noise-profile config keys (hide and demote domain sets, dedup default) with shipped defaults and unit tests; `src/vaultspec_rag/config.py`.

### Phase `P03` - Parity and verified improvement

Thread one filter contract through api, service route, CLI, and MCP, then prove a noise@k reduction against the recorded baseline and document the surface.

- [x] `P03.S06` - Thread the domain filter and profile contract identically through the facade, service search route, CLI flags, and the MCP tool, rejecting domain filters for vault search, with parity tests; `src/vaultspec_rag/server/_routes.py`.
- [x] `P03.S07` - Add a performance benchmark replaying the fixed query set against the live index asserting a noise@k reduction versus baseline, reindex and re-measure, and document the noise controls; `src/vaultspec_rag/tests/benchmarks/bench_search_noise.py`.

## Description

Implements the `search-noise-filtering` ADR. Code search on this repo measured
70.8% non-production hits and a 44.2% duplicate rate at `k=12`, the duplicates
almost entirely agent worktree clones echoing real `src/` files at identical
scores. The work introduces one shared, worker-safe domain classifier; persists
a per-chunk `domain` payload at index time for cheap pushdown; adds reversible
`--exclude-domain` / `--only-domain` filters and a demote-or-hide policy pass
with no-silent-depletion backfill; declares a persistent per-project noise
profile with shipped defaults; flips the conservative locale-dedup default on;
and threads one filter contract through every adapter. Success is a measured
noise@k reduction against the recorded baseline.

## Steps

## Parallelization

Phases are sequenced. P01 lands first: the shared classifier (`P01.S01`) is a
dependency of every later Step, and the index-time payload (`P01.S02`) must
precede the store pushdown. Within P02, `P02.S03` (store) and `P02.S05` (config)
are independent and may proceed in parallel; `P02.S04` (searcher) depends on
both. P03 is last: parity wiring (`P03.S06`) needs the P02 searcher surface, and
verification (`P03.S07`) needs the whole chain plus a reindex.

## Verification

- Pure-function unit tests pass for `classify_domain`, the demote-or-hide policy,
  the backfill loop, and noise-profile parsing, on CPU with no mocks.
- An integration test confirms code chunks carry the `domain` payload and that
  `--exclude-domain`/`--only-domain` filter via pushdown, with the post-query
  fallback exercised for un-backfilled chunks.
- A parity test asserts the in-process, service-route, CLI, and MCP paths share
  one filter contract and that domain filters are rejected for vault search.
- The `@pytest.mark.performance` benchmark replays the fixed query set against
  the live index and asserts noise@k drops materially below the recorded 70.8%
  baseline and the duplicate rate collapses.
- The full lint/type/markdown/complexity gate is clean and every Step is closed.
