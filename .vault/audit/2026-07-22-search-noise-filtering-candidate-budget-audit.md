---
tags:
  - '#audit'
  - '#search-noise-filtering'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:eada16c924594b90014b30ce66b74f13a2bc8b8597bf96cd2eff8d61f03e445d'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# `search-noise-filtering` audit: `candidate budget correction`

## Scope

Review the reopened P02.S04 candidate-budget correction against the accepted
search-noise architecture, Qdrant domain pushdown, missing-domain fallback,
reranker authority, and the repository's real-behavior test constraints.

## Findings

### candidate-window-amplification | high | resolved pushed filters no longer inherit glob overfetch

`VaultSearcher._fetch_codebase_candidates` treated every hard-domain policy as
a Python post-filter and started at `max(10 * top_k, 50)`, even though labeled
domain constraints were already present in the Qdrant query. The corrected
branch reserves that initial window for actual include/exclude path globs and
starts pushed-domain searches at the ordinary reranker budget. No critical or
high issue remains open.

### fallback-backfill | low | legacy missing-domain survivor recovery remains bounded

The existing widening loop still classifies rows without a stored domain,
counts dropped domains, and doubles only while survivors cannot fill the page.
A real Qdrant-local test removes domain payloads from stored points, places four
excluded test rows above two production rows, and verifies the two production
survivors are recovered with the exact drop count.

### test-integrity | low | production store behavior proves both candidate windows

The verification imports the production searcher, store, policy, and code chunk
types. It uses isolated Qdrant-local collections and real vector queries without
fakes, mocks, stubs, patches, monkeypatching, GPU models, skips, or expected
failures. With `top_k=5`, the reranker-enabled path returns the 20-row normal
window for pushed filters and the 50-row widened window for a Python glob.

## Recommendations

Close P02.S04 after the focused tests, Ruff format/check, BasedPyright, and vault
artifact validation remain clean. Keep the survivor-driven widening loop as the
sole expansion mechanism for legacy missing-domain depletion.
