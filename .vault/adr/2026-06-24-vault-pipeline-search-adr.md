---
tags:
  - '#adr'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-vault-pipeline-search-research]]"
---



# `vault-pipeline-search` adr: `intent-aware pipeline ranking and result shape for vault search` | (**status:** `accepted`)

## Problem Statement

Vault semantic search treats every document as one undifferentiated `--type vault` bucket
and ranks purely on topical relevance, so an agent orienting itself cannot separate the
authoritative architectural decisions from the implementation artifacts that share their
vocabulary. The sibling research reproduced this live: the orientation query "decision on
gpu lock scope" returns an execution step record at a calibrated rerank score of 0.8455 as
the top hit, while the `service-concurrency` ADR that the step implements scores only
0.4642 — retrieved, but out-ranked by its own artifact by a 0.38 margin. The results are
noisy, not wrong. The value of a vault document is *intent-relative*: for orientation the
hierarchy is adr/audit > research/reference > plan > exec; for debugging it inverts. This
ADR concretizes the rework that makes vault ranking and result shape mirror the vaultspec
pipeline and respond to declared intent. It is grounded in
`2026-06-24-vault-pipeline-search-research`.

## Considerations

- The vault search pipeline (`src/vaultspec_rag/search/_searcher.py`) runs hybrid RRF →
  CrossEncoder rerank (calibrated sigmoid [0,1]) → chunk grouping → graph rerank. Any
  pipeline-role prior must compose after the forward pass and outside the GPU lock, per
  the codified rules `gpu-lock-wraps-forward-passes-only` and `rerankers-score-real-content`.
- An in-tree precedent exists: `_apply_prefer_nudge` reweights by category post-rerank and
  re-sorts. But both existing reweighters (`--prefer` at `PREFER_SCORE_NUDGE = 0.05`, and
  the graph nudges at 0.005/0.03 in `src/vaultspec_rag/search/_rerank.py`) are explicitly
  bounded to "break ties only, never override semantic relevance." Crossing a 0.38 gap
  requires deliberately overriding relevance — the central tension this ADR resolves.
- ADR status lives in the H1 title (`| (**status:** value)`), not frontmatter, in two
  formats: modern (with the marker) and legacy 2026-03 ADRs (`# ADR: ...`, no marker).
  The status vocabulary is {proposed, accepted, rejected, superseded, deprecated} plus an
  implicit `unknown` for legacy headers.
- `related` is already extracted and persisted to the Qdrant payload but never mapped onto
  `SearchResult`; `status` is absent end-to-end. JSON output auto-serializes new
  `SearchResult` fields via `asdict`; human rendering surfaces none of them today.
- Ranking/intent/status logic must live in the search/service domain with the CLI as a
  thin adapter (`service-domain-owns-operability`); every parameter threads CLI → HTTP
  route → MCP `search_vault`, with a stable JSON envelope.

## Constraints

- No frontier risk: all components (CrossEncoder, Qdrant, the existing post-rerank seam)
  are mature and in-tree. The work is composition and surface, not new technology.
- Populating `status` in the payload requires a full vault reindex; the field is new and
  back-fill is not incremental. Legacy no-marker ADRs constrain the extractor to a
  tolerant regex with a defined `unknown` fallback.
- The intent prior is a tuning surface, not a proof: its correctness is only knowable
  through the validation instrument (D8). The instrument must therefore exist and capture
  a real baseline *before* the ranking change lands, or the change is unfalsifiable.
- Parent stability: the search pipeline, the `--prefer`/graph reweight seam, and the
  service-first routing are all shipped and stable; this ADR extends them rather than
  depending on anything in flight.

## Implementation

High-level, layered. A plan will sequence it.

**D1 — Intent is an explicit mode, never inferred.** Search takes a declared intent. Two
profiles ship first — `orientation` (default) and `debug` — selected by an explicit
`--intent orientation|debug` flag (extensible to a third `implementation` profile, plan/exec
lead, that the validation rubric in D8 already accommodates). Inference from query text is
rejected as unreliable and, fatally, unmeasurable. The default surfaces active ADRs.

**D2 — A multiplicative per-(type × status) ranking prior.** After the CrossEncoder
rerank and chunk grouping, each vault result's calibrated score is multiplied by a
per-(doc_type, status) weight drawn from the active intent profile, then the list
re-sorts. Multiplicative composition (over additive nudging or hard tiering) preserves
within-type relevance ordering, scales smoothly on [0,1], and lets a strong topical match
still win across types — while deliberately allowing a high-value type to overcome a
relevance gap. This is the intentional, bounded override of the "tie-break only"
philosophy: it is scoped to the type×status axis, gated on explicit intent, and inspectable.
The graph in-link/feature nudges remain bounded tie-breakers applied within the reweighted
ordering.

**D3 — Weights live in config, are legible and tunable.** The orientation and debug
profiles are configuration (per-type, per-status multipliers), not hard-coded constants, so
operators can inspect and tune them and the validation harness can sweep them. Indicative
orientation starting profile: adr/audit ≈ 1.0, research/reference ≈ 0.85, plan ≈ 0.6, exec
≈ 0.4; debug inverts exec/summary to the top. Status multipliers (orientation): accepted
and unknown ≈ 1.0, proposed ≈ 0.6, superseded/rejected/deprecated ≈ 0.3 — subject to
tuning against D8.

**D4 — Per-type cap to fight crowding.** A bounded cap on how many results of one doc_type
may occupy the returned top-k (or a decay on consecutive same-type hits) prevents a run of
exec records from burying the single ADR, independent of the score prior.

**D5 — Status extraction, vocabulary, and the `--status` control.** The indexer extracts
status from the H1 title with a backtick-tolerant regex in the same pass that
`_extract_title` already runs, and strips the `| (**status:** ...)` suffix from the
displayed title (fixing the current title-pollution). Legacy no-marker ADRs resolve to
`unknown`. Status-deranking is scoped to ADRs (the type whose authority decays on
supersession); other types are ordered by the type prior. `--status` defaults to the
active set (`accepted` + `unknown`) and a flag opts the rest back in (`--status all` or
explicit values). Status is a new payload field (D7) requiring a reindex.

**D6 — Doc-type union as first-class selection, back-compatible.** `--type vault` remains
the union of all indexable doc types; doc-type names become selectable as a union subset
(repeatable `--doc-type`, accepting multiple values), with the existing single-valued
`--doc-type` preserved. The indexable union is `research | reference | adr | audit | plan
| exec`; `index` is excluded as auto-generated navigational content. `audit` ranks in the
authoritative tier with ADRs.

**D7 — Frontmatter-enriched results.** `SearchResult` gains `related` and `status`. The
searcher maps `related` (already in the payload) and the new `status` payload field onto
the result; human rendering (`_display_search_results`) gains a metadata line surfacing
doc_type, feature, status, date, and related; JSON inherits the fields automatically. The
envelope stays stable across CLI, HTTP route, and MCP `search_vault`.

**D8 — The intent-aware validation instrument (shared acceptance gate).** A three-tier,
all-real-inference instrument, because the existing surfaces cannot grade role × intent:
`run_quality_probe` is a needle round-trip plumbing check, `run_benchmark` measures latency
only, and `test_quality.py` asserts only set-membership and coarse ordering.

Tier 1 — *offline graded metrics*. A `quality`-marked integration test drives a committed
labeled query set (~30–50 real queries, ~10–15 per intent) against a real index. Each query
declares its intent and a gold list of `(doc_id, grade)` judgments on a 0–3 scale assigned
*mechanically* from a declarative rubric keyed on (intent, doc_type, status) — authored
independently of any retriever output, which is what keeps it non-tautological. Indicative
rubric (topically-relevant docs only; off-topic = 0):

| doc_type / status | orientation | debugging | implementation |
| --- | --- | --- | --- |
| adr (accepted) | 3 | 1 | 2 |
| adr (proposed/superseded) | 1 | 0–1 | 1 |
| research / reference | 2 | 1 | 1 |
| plan | 1 | 1 | 3 |
| exec (step/summary) | 0–1 | 3 | 2 |
| audit | 1 | 2 | 1 |
| code chunk | 0 | 2 | 1 |

Metrics, reported per-intent (never blended): role-aware **NDCG@10** with gain = the rubric
grade (headline); orientation **Authoritative@3** (a grade-3 accepted ADR in the top 3) and
mean rank of the first grade-3 doc; debugging **MRR** of the first gold artifact; a
**role-precision@3** sanity guard; and the existing **needle-precision floor (≥0.75)** as a
hard no-regress guard. The live failure ("decision on gpu lock scope" → the
`service-concurrency` ADR must reach rank 1, not the matching exec record) is a named,
always-on regression test. A baseline is captured on the current ranking before D2 lands.

Tier 2 — *qualitative persona testimonials*. Extend the existing scripted-persona discipline
in `test_cli_ux_testimonial.py` (its `_Observation` dataclass records command, output, and
friction): one persona per intent issues live searches and records a structured verdict
against a `expected_authority` doc declared *before* the search runs, so the verdict is a
comparison to a pre-committed expectation, not a post-hoc rationalization. Verdicts are
asserted (the gate) and their notes persisted in the verification audit (the human-readable
signal) — the same data viewed two ways.

Tier 3 — *A/B delta report*: a regenerable before/after table of rank-1 doc and score per
gold query, embedded in the audit as the decision evidence.

Corpus: enrich the synthetic generator to emit status markers and pipeline (research→adr→
plan→exec) edges for a deterministic CI gate, with periodic runs against the real `.vault/`
for confidence. A precondition the instrument exposes: `status` must be surfaced onto
`SearchResult` and the payload (D5/D7) before any role × status metric can be computed.

**D9 — Search-quality tooling is test-suite tooling, not a production verb.** The
intent-aware instrument (D8) lands as a `quality`-marked pytest integration test under
`src/vaultspec_rag/tests/`, never a production CLI verb. The same responsibility split
applies to the already-shipping `vaultspec-rag quality` (`src/vaultspec_rag/cli/_quality.py`,
which builds a throwaway synthetic vault and runs needle probes) and `vaultspec-rag
benchmark` (`src/vaultspec_rag/cli/_benchmark.py`, a latency/VRAM micro-bench): both expose
developer regression tooling on a production-facing binary and even self-describe as "not a
report on your current project," yet ship to every operator. This ADR records the decision
to remove `quality` and `benchmark` from the production command group, retaining the
capability only in the marked test suite (`run_quality_probe`/`run_benchmark` in
`src/vaultspec_rag/api.py` move under the test tree or are deleted, leaving no orphaned
production entry point). Because this is a breaking CLI change distinct from the ranking
rework, it is sequenced as its own discrete, independently-gated step in the plan, not
coupled to the D2 prior. The production CLI then exposes only operator verbs (`index`,
`search`, `status`, `server`, `clean`, `install`, `uninstall`, `preprocess`).

**Deferred:** a hard-tiered "grouped by pipeline role" view mode, and graph-lineage rollup
(collapsing plan+exec under the governing ADR via `related`) — both valuable, both
sequenced after the scoring prior proves out.

## Rationale

The research established that the failure is ranking, not retrieval (F1), and that the
existing reweight seam is the right place but the wrong magnitude and philosophy (F2, F3).
Multiplicative composition (F4, option b) is the most defensible default because it
overrides relevance only as much as the type/status weight dictates while preserving
within-type ordering; hard tiering (option c) was rejected as too brutal for mixed-intent
queries and lineage rollup (option e) deferred as the largest build. Explicit intent (F6)
is chosen over inference precisely because the validation requirement (F7) demands a
measurable, declarable condition. Status extraction is cheap and local (F5) and `related`
is already persisted (F5/F6), so the result-shape work is mostly mapping and rendering. The
validation instrument is elevated to a first-class decision because the owner identified
metrics as the hard part and because an intent prior is unfalsifiable without a
role-weighted, baseline-anchored benchmark.

## Consequences

- Gains: orientation queries surface the authoritative, active decision first; debugging
  queries surface the implementation trail first; every result carries its pipeline
  context (feature, status, related) so a hit becomes an orientation entry-point. The
  reweight is inspectable under `--scores` and tunable in config.
- Costs and risks: the type×status weights are a tuning surface that can over- or
  under-correct; only D8 keeps them honest, and D8 is real work that must precede D2.
  Status requires a full reindex. The deliberate override of the "tie-break only"
  philosophy is a genuine reversal that must be bounded and documented so future agents do
  not "fix" it back to a nudge.
- Pathways opened: the per-(type×status) profile generalizes to recency and to other
  document corpora; the lineage rollup and grouped view become natural follow-ons; the
  intent-aware benchmark becomes the standing guard against ranking regressions.

## Implementation erratum (2026-06-24)

Two decisions changed shape at implementation time and are recorded here so the ADR matches
what shipped (surfaced by the final code review):

- **CLI surface is query tokens, not dedicated flags (amends D1/D5/D6).** D1's
  `--intent orientation|debug` flag, D5's `--status` control, and D6's repeatable doc-type
  flag are exposed on the CLI as inline query tokens - `intent:orientation`,
  `intent:debugging`, `status:active|accepted|...`, and `type:adr,plan` - parsed by the
  query parser, not as new `handle_search` options. A dedicated flag would breach the
  project's frozen `max-args = 23` lint ratchet (a codified "never raise" gate), and the
  token form is consistent with the existing `type:`/`lang:` filter-token UX. The explicit
  `intent` parameter is still carried end-to-end on the HTTP `/search` route and the MCP
  `search_vault` tool for programmatic callers; only the operator CLI uses the token. The
  doc-type union additionally accepts a comma list on the existing `--doc-type` option.

- **The second profile is named `debugging`, not `debug` (amends D1/D3 prose).** Config,
  the query set, the rubric, and the tests standardized on `debugging`; the CLI accepts
  `debug` as an alias. The D1/D3 prose wording `debug` is an erratum.

## Codification candidates

- **Rule slug:** `vault-ranking-prior-is-intent-scoped`.
  **Rule:** The vault doc-type/status ranking prior may override semantic relevance only
  under an explicitly declared intent mode, only on the type×status axis, and must remain
  inspectable (visible under `--scores`, configured by named weight profiles); structural
  graph signals stay bounded tie-breakers.

- **Rule slug:** `intent-ranking-changes-need-baseline-benchmark`.
  **Rule:** No change to vault ranking weights or composition lands without first
  capturing a baseline on the intent-aware graded-relevance benchmark and showing the
  headline metrics improve without regressing needle precision.

- **Rule slug:** `dev-tooling-stays-out-of-production-cli`.
  **Rule:** Developer-only quality, benchmark, and test-harness capabilities live in the
  marked test suite, never as verbs on the production-facing `vaultspec-rag` CLI; operator
  surfaces expose only operator capabilities.
