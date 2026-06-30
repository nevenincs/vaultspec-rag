---
generated: true
tags:
  - '#index'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - '[[2026-06-30-search-noise-filtering-P01-S01]]'
  - '[[2026-06-30-search-noise-filtering-P01-S02]]'
  - '[[2026-06-30-search-noise-filtering-P01-summary]]'
  - '[[2026-06-30-search-noise-filtering-P02-S03]]'
  - '[[2026-06-30-search-noise-filtering-P02-S04]]'
  - '[[2026-06-30-search-noise-filtering-P02-S05]]'
  - '[[2026-06-30-search-noise-filtering-P02-summary]]'
  - '[[2026-06-30-search-noise-filtering-P03-S06]]'
  - '[[2026-06-30-search-noise-filtering-P03-S07]]'
  - '[[2026-06-30-search-noise-filtering-P03-summary]]'
  - '[[2026-06-30-search-noise-filtering-adr]]'
  - '[[2026-06-30-search-noise-filtering-plan]]'
  - '[[2026-06-30-search-noise-filtering-research]]'
---

# `search-noise-filtering` feature index

Auto-generated index of all documents tagged with `#search-noise-filtering`.

## Documents

### adr

- `2026-06-30-search-noise-filtering-adr` - `search-noise-filtering` adr: `query-time domain noise filtering, ranking, and a persistent noise profile` | (**status:** `accepted`)

### exec

- `2026-06-30-search-noise-filtering-P01-S01` - Create a worker-safe pure classify_domain(path) returning prod/tests/docs/locale/generated/vendored/worktree, supersede the prefer classifier to consume it, with unit tests
- `2026-06-30-search-noise-filtering-P01-S02` - Write a per-chunk domain payload at code index time, add domain to the code KEYWORD index set ensuring the index idempotently on existing collections, and exclude nested worktree clone dirs from the scan
- `2026-06-30-search-noise-filtering-P01-summary` - `search-noise-filtering` `P01` summary
- `2026-06-30-search-noise-filtering-P02-S03` - Extend the code filter builder for domain must/must_not pushdown driving exclude-domain and only-domain
- `2026-06-30-search-noise-filtering-P02-S04` - Add the post-rerank apply_domain_policy demote-or-hide pass, resolve exclude/only/include-domain, add the backfill loop with a filtered envelope note, and flip dedup-locales default on, with unit tests
- `2026-06-30-search-noise-filtering-P02-S05` - Add noise-profile config keys (hide and demote domain sets, dedup default) with shipped defaults and unit tests
- `2026-06-30-search-noise-filtering-P02-summary` - `search-noise-filtering` `P02` summary
- `2026-06-30-search-noise-filtering-P03-S06` - Thread the domain filter and profile contract identically through the facade, service search route, CLI flags, and the MCP tool, rejecting domain filters for vault search, with parity tests
- `2026-06-30-search-noise-filtering-P03-S07` - Add a performance benchmark replaying the fixed query set against the live index asserting a noise@k reduction versus baseline, reindex and re-measure, and document the noise controls
- `2026-06-30-search-noise-filtering-P03-summary` - `search-noise-filtering` `P03` summary

### plan

- `2026-06-30-search-noise-filtering-plan` - `search-noise-filtering` plan

### research

- `2026-06-30-search-noise-filtering-research` - `search-noise-filtering` research: `query-time domain exclusion and noise control for code search`
