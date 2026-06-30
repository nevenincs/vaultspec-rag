---
tags:
  - '#research'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-30'
related:
  - "[[2026-06-07-sparse-search-latency-adr]]"
  - "[[2026-06-08-sparse-search-latency-plan]]"
---

# `sparse-search-latency` research: `qdrant glob pushdown feasibility`

Verification of the Phase `P02` abort claim and investigation of a native Qdrant
pushdown for codebase path-glob filters (`include_paths` / `exclude_paths`), so the slow
Python `fnmatch` post-filter could be narrowed inside Qdrant before RRF fusion. Raised as
an explicit follow-up to the `P02` abort recorded in the ADR and the `P02.S04` execution
record.

## Findings

### Claim under test

The `P02` abort states that qdrant-client 1.18.0 forbids regex `MatchPattern` on payload
fields, so the glob-to-Qdrant pushdown was abandoned and the Python `fnmatch` post-filter
retained.

### Evidence (qdrant-client 1.18.0, the pinned version)

- `MatchPattern` (regex) genuinely does not exist in `qdrant_client.models`. The available
  string matchers are `MatchValue` (exact), `MatchAny`, `MatchExcept`, and `MatchText` /
  `MatchTextAny` (full-text). The literal claim is therefore TRUE: there is no regex
  payload filter.
- Full-text filtering IS supported: `MatchText` against a field carrying a
  `TextIndexParams(type=TEXT, tokenizer=...)` index (tokenizers include `WORD`,
  `WHITESPACE`, `PREFIX`, `MULTILINGUAL`). The abort note's broader phrasing — that Qdrant
  does not natively support payload text filtering — is therefore incomplete.
- Decisive constraint for this project: in local in-process mode, Qdrant emits the warning
  "Payload indexes have no effect in the local Qdrant. Please use server Qdrant if you need
  payload indexes." `MatchText` still filters functionally in local mode (verified: a token
  matching one point returned only that point, and an absent token returned none) but only
  as an UNINDEXED scan, with no acceleration.

### Why the abort outcome holds (with a corrected rationale)

- The dominant local-mode cost is the SPLADE sparse linear scan (~20s across ~114k chunks
  per the ADR). A payload filter applied during that scan does not avoid the scan, so a
  local pushdown yields little or no latency win.
- `MatchText` is tokenized text matching, not glob: it cannot reproduce `fnmatch` semantics
  (segment-aware `*`, `**`, brace sets). Substituting it for `fnmatch` would change result
  correctness.
- Net: retaining the Python `fnmatch` post-filter for local mode is the correct outcome.
  The abort's stated reason (the missing `MatchPattern` type) is true but partial; the
  fuller reason is the combination of no regex matcher, local-mode payload indexes having
  no effect, and `MatchText` not being glob-equivalent.

### Where a pushdown does become viable

In server / dedicated Qdrant (`VAULTSPEC_RAG_QDRANT_URL`, already formalized in the ADR),
payload indexes — including full-text — take effect, and the sparse inverted index removes
the SPLADE full-scan. There, a `TEXT` payload index on the project-relative path plus a
coarse `MatchText` or prefix pre-filter can narrow candidates natively before RRF, with
`fnmatch` retained only as an exact-glob refinement. This is a server-mode optimization,
not a local one.

### Recommendation

- Keep `P02` aborted for local mode, and correct the ADR's `P02` rationale to the reason
  above: the blocker is local-mode payload indexing plus glob-vs-text-match semantics, not
  merely the absent `MatchPattern` type.
- Track the server-mode path pre-filter (`TextIndexParams` + `MatchText` / prefix +
  `fnmatch` refine) as a follow-up tied to the server-mode work under `#165`, gated on a
  real server-mode deployment so the win can be benchmarked.
