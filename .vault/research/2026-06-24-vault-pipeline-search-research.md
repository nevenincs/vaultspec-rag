---
tags:
  - '#research'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-07-27'
body_hash: 'sha256:9c680f1f553e77c173edbc43d3c20411bde9b044e1b28fcc1270bec3ca5225f7'
related: []
---

# `vault-pipeline-search` research: `intent-aware pipeline ranking for vault search`

## Findings

### Retained preamble

Vault semantic search is useful but noisy: it treats every vault document as one
undifferentiated `--type vault` bucket and ranks purely on topical relevance, so an agent
trying to orient itself cannot disentangle the authoritative architectural decisions from
the implementation artifacts that share the same vocabulary. This research grounds â€” with
live searches against the running service and reads of the search, indexer, and CLI
source â€” the rework that makes vault results mirror the vaultspec pipeline hierarchy and
respond to the searcher's *intent*. It feeds one or more ADRs covering ranking
composition, document-status awareness, the search-type/CLI surface, and the validation
instrument. The driving requirements (owner-stated): default search must surface active
ADRs; status-based deranking must be manually controllable from the CLI; results must
carry frontmatter (feature tag, related documents, status); and quality must be proven by
metrics plus agent-persona live-search testimonials.

### F1 â€” The pollution, reproduced and quantified

Vault documents carry equal topical footing regardless of pipeline role, and the
cross-encoder rewards the document whose prose most echoes the query â€” which is routinely
an execution record, not the decision it implements. Live, against the running service:

| Query (intent: orientation)  | Top hit today                  | Score  | The authoritative doc                        |
| ---------------------------- | ------------------------------ | ------ | -------------------------------------------- |
| "decision on gpu lock scope" | exec step record `W03-P06-S15` | 0.8455 | `service-concurrency` adr scores only 0.4642 |

The decision record is *retrieved* â€” it surfaces immediately under `--doc-type adr` â€” but
it is *out-ranked* by its own implementation artifact by a 0.38 margin on the calibrated
[0,1] rerank scale. This is the core finding: the problem is ranking, not retrieval. The
results are noisy, not wrong. An orientation query should rank the accepted decision
first; a debugging query should rank the step record first. The value of a document is
*intent-relative*, and nothing in the current pipeline models that.

### F2 â€” Current search pipeline and where a prior must compose

The vault path in `src/vaultspec_rag/search/_searcher.py` (`_search_vault_encoded`) runs:
encode (Qwen3 dense + SPLADE sparse, cached) â†’ Qdrant hybrid search with RRF fusion â†’
map rows to `SearchResult` â†’ CrossEncoder rerank (replaces the score with a calibrated
sigmoid [0,1] value, re-sorts) â†’ `_group_chunks_by_document` (one row per document) â†’
`rerank_with_graph` (additive graph nudges, re-sort) â†’ truncate to `top_k`.

A pipeline-role/status prior must compose *after* the cross-encoder forward pass and
outside the GPU lock, honouring the codified rules `gpu-lock-wraps-forward-passes-only`
and `rerankers-score-real-content`. The natural seam is alongside `rerank_with_graph`, on
the grouped one-row-per-document list.

There is a direct in-tree precedent: `_apply_prefer_nudge` (the codebase `--prefer`
control) applies `Â±PREFER_SCORE_NUDGE` to results by a path-derived category and re-sorts.
It is exactly the shape we need â€” a post-rerank, category-driven reweight â€” but its
magnitude (`PREFER_SCORE_NUDGE = 0.05` in `src/vaultspec_rag/search/_postprocess.py`) is
deliberately tiny.

### F3 â€” The codified "tie-break only" tension

Both existing post-rerank reweighters are explicitly bounded to *never override semantic
relevance*. `src/vaultspec_rag/search/_rerank.py` sets `_IN_LINK_NUDGE_STEP = 0.005` and
`_FEATURE_NEIGHBOR_NUDGE = 0.03` with the comment that "structural graph signals must only
break ties and near-ties, never override semantic relevance." `--prefer` is documented as
re-ordering "ties and near-ties only."

The new requirement contradicts this philosophy head-on: to lift an accepted ADR (0.4642)
above an exec record (0.8455) for an orientation query, a structural signal must override
a 0.38 relevance gap. This is the single most important decision for the ADR â€” the prior
is no longer a tie-breaker, it is a first-class ranking term whose strength is conditioned
on declared intent. The resolution is to make the override *intentional and bounded*: it
applies only in orientation mode, only to the typeÃ—status dimension, and it must remain
inspectable (scores visible under `--scores`, weights configurable). The graph in-link and
feature nudges stay tie-breakers within a role tier.

### F4 â€” Ranking-composition design space

Strategies considered for injecting the intent-conditioned doc-type Ã— status prior:

- **(a) Additive nudge (the `--prefer` shape, scaled up).** Add a per-(type,status)
  offset to the calibrated score, then re-sort. Simple, inspectable, reuses the existing
  pattern. Risk: on a [0,1] scale a single additive constant either under-shoots (cannot
  cross a 0.38 gap) or over-shoots (pins an entire type to the top regardless of
  relevance). Tuning is brittle because the offset competes with an already-normalized
  score of unbounded relative gap.
- **(b) Multiplicative weight.** Multiply the calibrated score by a per-(type,status)
  factor (e.g. adrÃ—1.0, planÃ—0.7, execÃ—0.5 in orientation; inverted in debug). Composes
  smoothly with the [0,1] score, preserves within-type relevance ordering, and the
  weight is a legible knob. A weak topical match in a high-value type can still lose to a
  strong match â€” generally desirable. This is the most defensible default.
- **(c) Hard tiering then sort-within-tier.** Partition results into ordered role tiers
  (orientation: adr â†’ research/reference â†’ plan â†’ exec) and sort by relevance inside each
  tier. Guarantees the hierarchy but is brutal: a perfectly-matching exec record can never
  outrank a barely-relevant ADR, which is wrong for mixed-intent queries and removes the
  reranker's signal across tiers. Useful as an explicit "grouped" view, not the default
  ranking.
- **(d) Diversification / per-type caps (MMR-style).** Cap how many of one type may
  occupy the top-k, or penalize the Nth consecutive same-type hit. Directly attacks the
  "eight exec records crowd out the one ADR" failure without distorting individual scores.
  Cheap, complementary to (a)/(b) rather than a replacement.
- **(e) Graph-lineage rollup.** Use the `related` edges to collapse a plan and its exec
  records *under* the governing ADR, returning the ADR as a canonical node with its
  lineage attached. Most faithful to "mirror the pipeline" and turns a hit into an
  orientation entry-point, but it is the largest build and depends on reliable
  `related`/lineage edges; best sequenced after the scoring prior lands.

**Recommendation for the ADR:** a multiplicative per-(type Ã— status) prior (b) as the
default ranking term, conditioned on an explicit intent mode, with a small per-type cap
(d) layered on to fight crowding. Weights live in config so they are tunable and
inspectable; the graph in-link/feature nudges remain bounded tie-breakers applied within
the reweighted ordering. Tiering (c) and lineage rollup (e) are deferred / optional view
modes. The prior must be visible: `--scores` should show the composed score so the
override is never silent.

### F5 â€” Document status: vocabulary, location, extraction

Status is **not** in frontmatter. It is encoded in the ADR H1 title line, in the canonical
vaultspec-core template form:

`# {feature} adr: {title} | (**status:** {value})`

Two title formats coexist in the live vault:

- **Modern** (2026-04 onward): carries the `| (**status:** value)` status suffix.
- **Legacy** (the 2026-03 batch, e.g. `manual-node-walking`, `score-normalization`):
  `# ADR: {description}` with **no** status token at all.

Status values observed in real ADRs: `accepted`, `proposed`, `superseded`. The template's
enumerated set adds `rejected` and `deprecated`, and vaultspec-core's `set_superseded`
writes `superseded` into the H1 â€” so the full vocabulary is **{proposed, accepted,
rejected, superseded, deprecated}**, plus a sixth implicit state: **unknown** (legacy
ADRs with no token).

Extraction is cheap and local: a regex over the same H1 line that `_extract_title` in
`src/vaultspec_rag/indexer/_vault_prep.py` already reads, tolerant of optional backticks
around the value. The same pass should **strip** the `| (**status:** ...)` suffix from the
displayed title â€” today `_extract_title` returns the whole H1 including the marker, a
latent title-pollution bug. Legacy/no-token ADRs resolve to `unknown` and must be treated
as active (not deranked) so historical decisions are not silently buried.

Status-deranking is meaningful primarily for ADRs (the type whose authority decays on
supersession). Non-ADR types have no `(**status:** ...)` marker; their "freshness" is
better expressed through the type-prior and (optionally) recency than through a status
axis. The ADR should scope status-deranking to ADRs and let the type-prior order the rest.

Storage impact: `related` is already extracted (`_vault_prep.py`) and **already persisted
to the Qdrant payload** (`src/vaultspec_rag/store.py` writes `"related"` on both the
document and chunk upserts) â€” it is simply never mapped onto `SearchResult`. `status` is a
genuinely new payload field, requiring an indexer extraction, a `store.py` payload
addition, and a full reindex to populate.

### F6 â€” Search-type surface, CLI shape, and result rendering

The current surface (`src/vaultspec_rag/cli/_search.py`): `--type` is hard-validated to
`{docs, vault, code}` (`_validate_search_type`, with `docs` canonicalized to `vault`);
vault filtering is a thin `--doc-type / --feature / --date / --tag` set, single-valued,
threaded CLI â†’ `_try_http_search` â†’ server route â†’ `VaultSearcher`. Code search by
contrast has a rich filter surface (`--language`, `--include-path`, `--prefer`, etc.).

`SearchResult` (`src/vaultspec_rag/search/_models.py`) carries `doc_type/feature/date/ title` but **not** `related` and **not** `status`. The searcher maps only the former from
the Qdrant row.

Rendering: `--json` serializes the dataclass via `asdict` inside the stable envelope
`{ok, command, data:{query, search_type, via, results[]}}`, so **any new `SearchResult`
field auto-flows to JSON**. Human rendering (`_display_search_results` in
`src/vaultspec_rag/cli/_render.py`) prints only a location line, an optional score, and the
body text â€” it surfaces **no** doc-type, feature, related, or status for vault hits.
Frontmatter-in-results is therefore a new metadata line in this renderer plus two new
mapped fields; the JSON side is nearly free.

Proposed surface (for the ADR to ratify):

- **Doc-type union as first-class selection**, with back-compat: keep `--type vault` as
  the union of all indexable doc types, and accept doc-type names as the selection (e.g. a
  repeatable `--doc-type adr --doc-type plan`, or a comma list) so a union subset is
  expressible. The union is `research | reference | adr | audit | plan | exec`; **`index`
  is excluded** (auto-generated navigational document-lists with no semantic value). Note
  `audit` belongs in the authoritative tier alongside ADRs, not buried with exec.
- **Explicit intent mode**, default = orientation (surfaces active ADRs). A flag such as
  `--trace` / `--debug` selects the inverted (exec-first) weight profile. Intent is never
  inferred from query text â€” inference is both unreliable and unmeasurable.
- **`--status` control** for ADR deranking: default surfaces active (`accepted`, plus
  `unknown` legacy) and deranks `superseded/proposed/rejected/deprecated`; a flag opts
  those back in (`--status all`, or explicit values).
- **Frontmatter-enriched results**: each vault hit renders `doc_type`, `feature`,
  `status`, `date`, and `related[]`, in both human and JSON output.

Per the codified `service-domain-owns-operability` rule, ranking/intent/status logic lives
in the search/service domain; the CLI is a thin adapter. Every new parameter threads CLI â†’
HTTP route query params â†’ MCP tool (`search_vault`), and the JSON envelope stays stable
across all three adapters.

### F7 â€” Validation: the hard part

Three evaluation surfaces ship today, none able to grade role Ã— intent. `run_quality_probe`
(`src/vaultspec_rag/cli/_quality.py`, `src/vaultspec_rag/api.py`) builds a synthetic vault
and runs binary needle-in-haystack probes â€” each asserts a uniquely-tokened document
*appears*; it is an exact-match plumbing check, not a ranking measure. `run_benchmark`
(`src/vaultspec_rag/cli/_benchmark.py`) measures latency/VRAM only, never scoring relevance.
`test_quality.py` (`src/vaultspec_rag/tests/integration/test_quality.py`) is closest â€” it
asserts set-membership ("an ADR query returns *some* ADR"), filter correctness, needle-in-
top-k, and a coarse authority-boost average â€” but none of it grades *which* relevant
document should rank first. The synthetic corpus (`src/vaultspec_rag/synthetic.py`) is
role-flat: no status, no pipeline edges, no authority hierarchy, so it cannot even express
"the accepted ADR is the authoritative answer." None of these answers "is the authoritative
document ranked first *for this intent*" â€” there is no graded relevance, no rank-position
metric, and no role/status notion. They are the wrong instruments for this rework. They are
also a surface-responsibility defect independent of the rework: `quality` and `benchmark`
ship developer regression tooling on a production-facing binary and should be removed from
the production CLI, their capability retained only in the marked test suite.

The value function is **role Ã— intent weighted**, so the relevance rubric must encode it:

- **Graded-relevance rubric.** For a query tagged with an intent, assign each candidate a
  graded relevance from its (type, status) under that intent â€” e.g. in orientation an
  accepted ADR on-topic = highest grade, research/reference/audit = high, plan = medium,
  exec = low; a superseded ADR is demoted a grade; in debug/trace the exec/summary grades
  rise and the ADR becomes context. Grades are assigned by a human author per query, not
  derived from the system under test (avoiding tautology).
- **Offline metrics.** (i) **NDCG@k** with the role-aware graded relevance â€” the headline
  ranking-quality number. (ii) An orientation-specific **"rank of the first authoritative
  accepted ADR"** (and an "authoritative-doc-in-top-3" rate) â€” directly measures the F1
  failure. (iii) **MRR** of the first correct exec/summary for debug-intent queries.
  Report per-intent, never pooled.
- **Labeled query set.** A modest set (~20â€“40 queries) over the *real* project vault,
  each tagged with intent and a hand-authored gold judgment list, committed to the repo.
  This respects the project's no-mock / real-inference mandate: judgments are authored by
  a human against real documents, and the harness runs real GPU + real Qdrant + real
  models.
- **Qualitative gate â€” agent-persona testimonials.** Structured, not vibes, and not new:
  the repo already runs scripted operator personas in
  `src/vaultspec_rag/tests/integration/test_cli_ux_testimonial.py`, recording each step as a
  structured `_Observation` (command, output, friction). Extend that discipline to ranking â€”
  one persona per intent, each declaring its `expected_authority` document *before* the
  search runs (drawn from the gold set), so the verdict is a comparison to a pre-committed
  expectation, not a post-hoc rationalization. Verdicts are asserted (the gate) and their
  notes persisted in the audit (the human-readable signal): the same data viewed two ways.

**Recommended acceptance instrument for the ADR:** a new intent-aware ranking benchmark
(NDCG@k + orientation-rank + debug-MRR over the committed labeled set) that captures a
baseline on the current ranking and must improve on the headline metrics without
regressing the existing needle precision, backed by the structured persona testimonials.
Build the benchmark *before* the ranking change so the baseline is real.

### F8 â€” Open decisions to concretize in the ADR(s)

- Ranking composition: confirm multiplicative per-(typeÃ—status) prior + per-type cap as
  default; ratify whether tiering and lineage-rollup ship as optional view modes or are
  deferred entirely.
- The concrete default weight profiles for orientation and debug intents, and where they
  live (config keys, so they are tunable and inspectable).
- Intent-mode flag naming and default; `--status` flag semantics and default "active" set
  (does `unknown` count as active â€” recommended yes).
- Doc-type union flag ergonomics and back-compat contract for `--type vault` / existing
  `--doc-type`; confirm `audit` in, `index` out.
- New `SearchResult` fields (`related`, `status`) and the reindex/migration needed to
  populate `status` in the payload.
- Whether this is one ADR or a small set (candidate split: a ranking/status ADR and a
  CLI-surface/result-shape ADR, sharing the validation instrument).

## Sources

No separate sources is recorded in the retained prior research body. Source: retained prior research body.
