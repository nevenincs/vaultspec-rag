---
tags:
  - '#audit'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
related: []
---

# `vault-pipeline-search` audit: `live persona testimonials`

## Scope

Live manual validation (Wave W06) of the shipped intent-aware vault ranking against the
real, existing project vault (~694 documents), driven by agent personas issuing realistic
searches through the new code. Two personas were exercised: an *orienting newcomer*
(orientation intent) and a *debugging maintainer* (debugging intent). The purpose was the
human-credible qualitative gate the ADR's D8 calls for - confirming on the real corpus what
the curated automated gold set cannot, and surfacing anything the gold set missed.

## Findings

### F1 (HIGH, fixed during this audit): auto-generated index documents leaked into results

The first persona run exposed that `index/` feature-index documents - auto-generated
navigational document-lists - were not only present in vault results but **ranked first**:
`index/qdrant-server-provisioning.index` led the qdrant query at score 0.992,
`index/watcher-targeted-reindex.index` led the watcher query at 0.839, and
`index/mcp-service-client.index` placed mid-page on the mcp query. An index file lists every
document of its feature, so the cross-encoder scores it very high on any feature-named query.

ADR D6 decided index is excluded as navigational noise, but the implementation enforced that
only as a rejected *filter value* (`INDEXABLE_DOC_TYPES`) - it never stopped index documents
from being indexed or from surfacing in unfiltered results. This is exactly the pollution D6
intended to prevent, and the curated gold set never caught it because it lists no index docs.

Fixed in this audit: the vault searcher now drops `doc_type == "index"` rows before rerank,
so index documents never surface, with a regression guard in the intent-ranking harness.

### F2: persona testimonials - the prior surfaces the right authority

After the F1 fix, the recorded testimonials (top result shown; `[doc_type|status|feature]`):

- *orienting newcomer*, "how is concurrent search saturation handled" -> **accepted
  service-concurrency ADR at rank 1** (0.612). Verdict: satisfied.
- *orienting newcomer*, "qdrant server mode binary provisioning" -> **accepted
  qdrant-server-provisioning ADR at rank 1** (0.991). Verdict: satisfied.
- *orienting newcomer*, "mcp service client architecture" -> **accepted mcp-service-client
  ADR at rank 1** (0.886). Verdict: satisfied.
- *debugging maintainer*, "narrow the gpu lock to forward calls in search" -> **exec record
  W03-P06-S15 at rank 1** (0.992), with the ADR correctly demoted to rank 3. Verdict:
  satisfied.
- *debugging maintainer*, "watcher leaves stranded pending changes" -> **exec record at rank
  1** (0.623). Verdict: satisfied.

Both personas consistently received the artifact matching their intent, and every surfaced
result carried its pipeline frontmatter (type, status, feature) - the orientation persona
could see at a glance which ADRs were `accepted`.

### F3 (LOW, tuning): one orientation query ranks the accepted ADR at rank 2

For "decision on gpu lock scope" the accepted service-concurrency ADR lands at rank 2 (0.464),
narrowly behind a tangential preprocess-hooks research document (0.475) whose body happens to
discuss `gpu_lock`. The prior demotes the implementing exec record correctly (to rank 3), and
Authoritative@3 still counts this query as a hit, but the off-topic research doc edges the ADR
by 0.011. This is a cross-encoder topical-relevance artifact the type prior nearly - but not
fully - overcomes at the current weights.

## Recommendations

- F1: keep the query-time index exclusion and its regression guard; optionally also skip
  indexing `index/` documents at index time as a defence-in-depth follow-up (would require a
  reindex).
- F3: monitor with a larger labeled set; if the pattern recurs, consider a modest increase to
  the orientation ADR/research weight gap or a small recency or same-feature signal. Not a
  blocker - the acceptance gate (Authoritative@3 = 0.833, the achievable ceiling) holds.
- The live persona run should be repeated against the running service once it is restarted on
  the new code and the real vault is reindexed (the service was on three-day-old code during
  this audit; testimonials were captured via the in-process path on the new code).

## Codification candidates

- **Source:** finding F1 (index documents leaked into vault results).
  **Rule slug:** `index-docs-excluded-from-vault-search`.
  **Rule:** Auto-generated feature-index documents must be excluded from vault search results
  at query time, not merely rejected as a doc-type filter value; a type marked non-searchable
  must never surface in unfiltered results.
