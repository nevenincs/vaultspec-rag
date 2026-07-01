---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# `search-noise-filtering` `P03` summary

One filter contract across every adapter, and a measured noise@k improvement.

- Created: `src/vaultspec_rag/tests/benchmarks/bench_search_noise.py`
- Modified: `src/vaultspec_rag/search/_validation.py`,
  `src/vaultspec_rag/search/_parsing.py`,
  `src/vaultspec_rag/search/_searcher.py`, `src/vaultspec_rag/api.py`,
  `src/vaultspec_rag/server/_routes.py`,
  `src/vaultspec_rag/serviceclient/_transport.py`,
  `src/vaultspec_rag/cli/_search.py`, `src/vaultspec_rag/mcp/_tools.py`,
  `src/vaultspec_rag/config.py`, `docs/search-and-index.md`,
  `docs/configuration.md`

## Description

The domain contract reaches the facade, service route (with a `filtered`
envelope field), CLI, and MCP. To respect the command's max-args ratchet, CLI
and HTTP carry domain filters as inline `exclude:` / `only:` / `include:` query
tokens (parsed server-side, merged with explicit kwargs); MCP keeps typed params
and encodes them to tokens. Validation rejects unknown domains and code-only
filters on vault search. Verification: a controlled-corpus performance benchmark
measured noise@10 falling 0.88 -> 0.40 with production results rising 7 -> 36
(5x), locale 26 -> 6, generated 6 -> 0, worktree clones absent; a deterministic
reranker-off variant gates the reduction. Full ruff / basedpyright / markdown
gate clean.
