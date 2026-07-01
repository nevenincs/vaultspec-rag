---
tags:
  - '#research'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - '[[2026-05-28-cli-search-filters-adr]]'
  - '[[2026-05-30-cli-path-glob-research]]'
  - '[[2026-05-31-search-postprocess-adr]]'
  - '[[2026-06-24-vault-pipeline-search-adr]]'
  - '[[2026-04-04-vaultragignore-research]]'
---

# `search-noise-filtering` research: `query-time domain exclusion and noise control for code search`

A testimonial from a large polyglot consumer repo reported that code search
returns noise it cannot suppress: parallel `locales/{en,es,ca,hu}.yml` return
four near-identical hits for one signal, test docstrings outrank the production
module, and "there doesn't seem to be a way to exclude file patterns from test
results." This research corroborates each claim against the shipped code,
separates what already exists from what is genuinely missing, and frames the
mechanisms needed to let a caller exclude a *known* noise domain at query time.

## Findings

### What already ships (the claims are partly out of date)

The shipped surface is larger than the testimonial assumed. Confirmed by reading
the search path end to end (`cli/_search.py`, `server/_routes.py`,
`search/_searcher.py`, `search/_postprocess.py`, `store.py`, `store_schema.py`):

- **Exact code filters** `--language`, `--path`, `--function-name`,
  `--class-name`, `--structure` (node type) are KEYWORD-indexed and applied as
  Qdrant `MatchValue` pushdown (`store._build_code_filter`). They are forwarded
  over the service HTTP fast path (`server/_routes.py` reads each from the JSON
  payload). The claim that these are "no-ops over `--port`" describes issue
  #107, which the `cli-search-filters` ADR closed: the fast path now shares the
  in-process filter contract.
- **Glob filters** `--include-path` / `--exclude-path` exist and are forwarded
  over HTTP. They are a *post-query* `fnmatch` pass in
  `_filter_raw_codebase_results`, not pushdown.
- **`--prefer prod|tests|docs`** applies a `+/-0.05` score nudge by path-derived
  category after rerank.
- **`--dedup-locales`** collapses recognised locale-variant paths
  (`_collapse_locale_variants`) to the highest scorer within a `0.10` score
  window.
- **Index-time exclusion** via `.vaultragignore` (shipped from the
  `vaultragignore` ADR) removes git-tracked files from the index entirely.
- **Vault search** carries an intent-conditioned `type x status` prior plus a
  per-type cap and status filter (`search/_intent_rank.py`); codebase results
  pass through that layer untouched.

So the user *can* type `--exclude-path "*test*" --dedup-locales`. The problem is
not a total absence of controls; it is that the controls are weak, off by
default, path-shaped rather than domain-shaped, and silent when they fail.

### Gap 1 - glob exclusion is overfetch-bounded and silently depletes

`--exclude-path` runs *after* retrieval over a fixed candidate budget. When a
glob filter is active the searcher fetches `max(top_k * GLOB_FETCH_MULTIPLIER, 50)` candidates (`GLOB_FETCH_MULTIPLIER = 10`), drops the matches in Python,
then reranks the survivors. It never re-queries to backfill. For exactly the
testimonial's case - a vocabulary-matched query where the test or locale surface
dominates the top candidates - exclusion returns a *depleted or empty* page with
no signal that results were dropped. This violates the project's own
"no silent caps - log what was dropped" stance (`operator-views-are-bounded`).

The `cli-path-glob` research recorded *why* it is post-query: qdrant-client has
no `MatchPrefix`/wildcard on a KEYWORD field, and converting `path` to a TEXT
index would break the exact-match `--path` contract and force a reindex. That
reasoning is sound for `path`, but it left the depletion behaviour unmitigated.

### Gap 2 - no semantic-domain exclude; the classifier exists but is under-used

`_classify_chunk_type(path)` already labels every result `prod | tests | docs`,
but it is wired *only* to the `--prefer` score nudge. There is no way to say
"exclude the tests domain" and have it apply regardless of where tests live -
`tests/`, `*_test.py`, `__tests__/`, an inline test module under `src/`. Path
globs require the caller to know the repo's test layout; a domain label does
not. The same gap covers `locales`, generated code, vendored trees, and
fixtures, none of which the three-category classifier even recognises.

### Gap 3 - noisy defaults

The two passes that directly answer the testimonial (`--dedup-locales` for the
four-locale problem, index-doc exclusion already on for vault) are opt-in for
code. A caller who never passes `--dedup-locales` gets the four-hit locale noise
by default - which is precisely the reported experience. The
`search-postprocess` ADR chose defaults-off for backwards compatibility; the
cost is that the default code-search experience is the noisy one.

### Gap 4 - no persistent, declarative noise profile

Every search must re-specify `--exclude-path`/`--prefer` tokens. There is no
per-project place to declare "in this repo, tests and locales are noise by
default; demote them, or hide them unless asked." `.vaultragignore` is the only
persistent knob and it is *index-time hard removal* - the wrong tool when a
caller wants tests *indexed and searchable on demand* but *excluded by default*.
The distinction between hide (hard, reversible per-call) and demote (soft,
recoverable) has no home today.

### Architectural anchors for the fix

- The post-rerank pure-pass pattern in `_intent_rank.py`
  (`apply_intent_prior` -> `apply_type_cap` -> `apply_status_filter`) is the
  template: classify, reweight or drop, re-sort, all outside the GPU lock. A
  codebase-domain pass is the symmetric counterpart of the vault intent prior.
- A *new* `domain` KEYWORD payload field on code chunks sidesteps the
  `cli-path-glob` pushdown objection entirely: it does not touch the `path`
  field's exact-match contract, and it makes domain exclusion a cheap Qdrant
  `must_not` pushdown rather than an overfetch-bounded Python pass. Classify once
  at index time (CPU-only, pure path logic - safe for the spawn workers per
  `index-workers-stay-cpu-only`), filter cheaply at query time.
- One pure `classify_domain(path)` shared by the index writer and the query-time
  fallback keeps a single source of truth and avoids the index/query drift that
  a duplicated classifier would invite. It supersedes `_classify_chunk_type`.
- Backfill (re-query a wider window when a hard exclude prunes below `top_k`)
  plus a `filtered` note in the result envelope resolves Gap 1 without changing
  the `path` contract.

### Verification approach

The acceptance gate is a measured drop in *noise@k* - the fraction of a top-k
page that is test/locale/generated/vendored - across a fixed query set run
against this repo's own live index, before and after. Pure-function unit tests
(classifier, backfill, profile parsing) need no GPU; the noise@k benchmark
exercises the real GPU + Qdrant path under `@pytest.mark.performance`, per the
testing mandates (no mocks, real inference).

## Open questions for the ADR

1. Does adding a `domain` payload field + KEYWORD index force a
   `STORAGE_SCHEMA_VERSION` bump and a disruptive machine-wide reindex, or can it
   be an additive optional field with query-time fallback classification for
   pre-existing chunks?
1. Hard-exclude (drop) vs soft-demote (nudge) as the *default* for the noise
   profile, and which domains ship as default-noise vs opt-in.
1. Where the persistent profile lives: a `[tool.vaultspec-rag]` config block vs a
   sibling dotfile, weighed against the existing config surface in `config.py`.
1. Whether default-on locale dedup is safe enough to flip without a deprecation
   window.
