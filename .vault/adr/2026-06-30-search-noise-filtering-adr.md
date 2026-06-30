---
tags:
  - '#adr'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-search-noise-filtering-research]]"
  - "[[2026-05-31-search-postprocess-adr]]"
  - "[[2026-05-30-cli-path-glob-research]]"
  - "[[2026-06-24-vault-pipeline-search-adr]]"
---

# `search-noise-filtering` adr: `query-time domain noise filtering, ranking, and a persistent noise profile` | (**status:** `accepted`)

## Problem Statement

Code search on a large polyglot repo returns a top page dominated by noise the
caller cannot reliably suppress. Measured on this repo's own live index over a
ten-query set at `k=12`: **70.8% of returned hits are non-production** and
**44.2% are duplicates**, the duplicates almost entirely agent worktree clones
under `.claude/worktrees/` that echo a real `src/` file at the *identical*
score. The shipped controls are real but insufficient: `--exclude-path` is a
post-query `fnmatch` over a fixed overfetch budget that silently depletes the
page when noise dominates; `--prefer` is a `+/-0.05` nudge over three hardcoded
path categories; `--dedup-locales` answers the four-locale complaint but is
off by default; and there is no way to exclude a *known noise domain* (tests,
locales, generated, vendored, worktree clones) without knowing its exact path
layout, nor to declare that domain once per project. This ADR decides the
mechanisms to give a caller durable, legible control over code-search noise.

## Considerations

- The research corroborated that the gap is not a missing flag but weak,
  path-shaped, default-off, silently-failing controls. The fix must be
  domain-shaped, persistent, and loud when it drops results.
- `search/_intent_rank.py` already establishes the post-rerank pure-pass pattern
  (classify, reweight or drop, re-sort) for vault results; codebase results pass
  through it untouched. A codebase-domain pass is the symmetric counterpart.
- `_classify_chunk_type(path)` already labels `prod | tests | docs` but is wired
  only to the `--prefer` nudge. A single shared classifier, widened to cover
  `locale | generated | vendored | worktree`, removes the duplication risk
  between an index-time writer and a query-time fallback.
- The `cli-path-glob` research established that qdrant-client cannot prefix- or
  wildcard-match a KEYWORD `path`, and that converting `path` to a TEXT index
  would break the exact `--path` contract. A **new** `domain` KEYWORD payload
  field sidesteps this entirely and makes domain exclusion a `must_not`
  pushdown instead of an overfetch-bounded Python pass.
- The `.claude/worktrees/` duplicates are transient clones of the same repo;
  indexing them is pure harm (wasted GPU, inflated store, perfect-duplicate
  noise). This is fixable at index time and complements the query-time layer.
- The `service-domain-owns-operability` rule requires the in-process, service
  HTTP, CLI, and MCP surfaces to share one filter contract, not drift.

## Considered options

- **A - widen `--exclude-path` only (status quo plus globstar).** Add `**`
  support and bump the overfetch multiplier. Rejected: still path-shaped (caller
  must know layout), still post-query and depletion-prone, still per-call with no
  persistence, and does nothing for the duplicate flood.
- **B - index-time hard removal only (extend `.vaultragignore` / hardcoded
  excludes to tests, locales, worktrees).** Rejected as the *whole* answer:
  removing tests from the index makes them unsearchable even when the caller
  wants them; the testimonial's need is "indexed but excluded by default,
  recoverable on demand." Kept *in part*: worktree clones are pure harm and are
  excluded at index time.
- **C - query-time domain layer + persistent profile + index-time domain payload
  for pushdown (chosen).** Classify every chunk into a domain once at index time;
  store it as a KEYWORD payload field; expose `--exclude-domain` / `--only-domain`
  as pushdown filters with a no-silent-depletion backfill; demote-or-hide domains
  by a per-project profile with per-call overrides; flip the conservative dedup
  default on. Reversible, domain-shaped, persistent, loud, and cheap at query
  time.
- **D - learned noise classifier / per-result ML scoring.** Rejected: over-
  engineered for a problem a pure path classifier solves; adds GPU cost and
  opacity where the `search-postprocess` ADR already chose a heuristic table.

## Constraints

- Index workers stay CPU-only and torch-free; the domain classifier must be a
  pure path function importable from the spawn worker chain
  (`index-workers-stay-cpu-only`).
- The new `domain` payload field is additive. Pre-existing chunks lack it, so
  query time must fall back to classifying `result.path` when the payload is
  absent; the field backfills on the next (incremental or full) reindex. If
  `assert_compatible` treats an index-set change as schema-incompatible, the
  storage-schema version bumps and the service's auto-reindex backfills - no
  manual migration step is exposed to operators.
- Reranker authority is preserved: domain *demotion* is a bounded post-rerank
  nudge (the CrossEncoder stays primary); only explicit *exclusion* (per-call
  flag or a profile `hide`) removes results.
- No new dependencies; `fnmatch` + `re` + the existing config surface only. No
  new silent `except` clauses; dropped-result counts are surfaced, not swallowed.
- Backwards compatibility: per-call flags and profile keys are additive; the one
  deliberate default change (locale dedup on, worktree domain hidden) is
  justified by the measured 70.8% noise and documented.

## Implementation

A single pure `classify_domain(path) -> Domain` in a worker-safe module becomes
the one source of truth, returning `prod | tests | docs | locale | generated | vendored | worktree`. It supersedes `_classify_chunk_type`; `--prefer` and the
new passes both consume it.

**Index time.** The codebase indexer computes `domain` per chunk and writes it
as a payload field; `domain` joins `CODE_KEYWORD_INDEXES` so it is pushdown-
filterable. The indexer's hardcoded scan exclusions gain nested git worktree
clone directories (e.g. `.claude/worktrees/`) so transient duplicates never
enter the index.

**Query time.** A new codebase pass mirrors `_intent_rank`: after rerank,
`apply_domain_policy` demotes domains by a bounded nudge and drops domains marked
`hide`. `--exclude-domain` / `--only-domain` (repeatable / comma) resolve to a
Qdrant `must_not` / `must` on the `domain` field when present, with a post-query
fallback for un-backfilled chunks. Hard exclusion (domain or glob) runs under a
backfill loop: if survivors fall below `top_k`, the searcher re-queries a wider
window until satisfied or the candidate pool is exhausted, and the response
envelope carries a `filtered` note (counts per dropped domain) so depletion is
visible, never silent.

**Persistent profile.** A `[tool.vaultspec-rag]` config block declares default
`hide` and `demote` domain sets (shipped defaults: hide `worktree`/`generated`,
demote `tests`/`docs`/`locale`) and the dedup-locales default. Per-call flags
override: `--include-domain` re-admits a hidden domain, `--no-dedup-locales`
disables the collapse.

**Parity and verification.** The contract threads identically through
`api`, `search/_searcher`, `server/_routes`, `cli/_search`, and the MCP tool. A
`@pytest.mark.performance` benchmark replays the fixed query set against the live
index and asserts a material noise@k reduction versus the recorded 70.8%
baseline; pure-function unit tests cover the classifier, backfill, and profile
parsing with no GPU.

## Rationale

The research showed the controls exist but fail in four specific ways; option C
addresses each at its root rather than papering over it. Classifying once at
index time and filtering by a dedicated payload field is the move the
`cli-path-glob` research could not make for `path` (its KEYWORD contract and the
reindex cost blocked a TEXT conversion) - a new field carries no such baggage and
turns exclusion into cheap pushdown. Demote-by-default preserves the
`search-postprocess` ADR's "demote, don't hide" principle for ambiguous domains
while reserving hard hide for the unambiguous-harm worktree duplicates the
measurement exposed. The persistent profile answers "when the domain is known,
exclude it" literally: declare it once. The 70.8% / 44.2% baseline makes the one
default change a correction, not a surprise.

## Consequences

- Code search returns a production-first page by default; the measured noise and
  duplicate rates should drop sharply, verified by the benchmark gate.
- A new payload field and KEYWORD index mean a schema touch; the additive design
  plus query-time fallback keeps operators from a manual migration, but a
  one-time background reindex backfills `domain` (auto-driven by the service).
- The shared classifier is a small ongoing surface: new noise conventions (a new
  vendoring dir, a new test layout) are one table edit, applied at both index and
  query time at once.
- `--prefer` is retained but now layered over the richer classifier; its
  three-category contract is unchanged for callers.
- A codification candidate falls out: "code-search noise is filtered by a shared
  domain classifier, demote-by-default with hard hide reserved for duplicate
  trees, never by silent overfetch truncation."
