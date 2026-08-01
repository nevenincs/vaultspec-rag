---
tags:
  - '#research'
  - '#search-index-availability'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:dad966fab0131f2a7d1a8ee7c0b25fa36316dde5ddd1107429e7354582025fa7'
related:
  - "[[2026-06-11-search-freshness-and-empty-results-adr]]"
  - "[[2026-06-11-server-bound-search-production-readiness-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
---

# `search-index-availability` research: `authoritative search outcomes during index convergence`

Issue 252 reports that an empty HTTP search response can look authoritative while matching
index work is still changing the requested corpus. This research bounds the immediate
false-negative fix and its relationship to the active job-control and generation-ledger
campaigns. Repository setup and ordinary usage remain in `README.md`,
`docs/getting-started.md`, `docs/installation.md`, `docs/search-and-index.md`, and
`docs/service-mode.md`.

Here, HTTP means Hypertext Transfer Protocol, CLI means command-line interface, MCP means
Model Context Protocol, and GPU means graphics processing unit. An authoritative empty
response is one that an automated caller may safely interpret as no match. Convergence means
an index job is moving one exact project root and source toward the files currently on disk.

## Findings

### The shipped response violates accepted intent

The accepted empty-search decision requires service search to distinguish a genuine no-match
from missing, stale, target-mismatched, or contended index state and to attach a known active
job. The route instead derives `index_state.status` only from the current count: zero becomes
`missing`, and every positive count becomes `available`. It classifies an empty result only as
`index_missing` or `no_match`, then returns the default HTTP 200. See
`src/vaultspec_rag/server/_routes.py:210-251` and
`src/vaultspec_rag/server/_routes.py:349-494` at commit
`a5881646a61b41daef989d4c5dd7010fe32f643b`.

Live evidence on 2026-07-21 confirmed that `/health` can report `ready` while multiple index
jobs run. Those jobs carry source and project-root attribution, yet the search response does
not consult it. GitHub issue 252 records the independent product bug:
https://github.com/nevenincs/vaultspec-rag/issues/252.

### Counts are not an availability authority

A clean vault or code rebuild drops and recreates its collection. During that destructive
interval, a zero count means rebuilding rather than missing. A positive count can still be a
partial generation whose later documents have not landed. The relevant production paths are
the clean branches of `VaultIndexer.full_index` and `CodebaseIndexer.full_index` at the pinned
commit.

The accepted large-index-resilience decision supplies the complete future authority: a clean
generation records destructive intent and remains `rebuild_incomplete` until valid
publication. Automatic incremental work can escalate to a clean rebuild, so an initial
request mode alone cannot replace this generation state.

### Active jobs are a narrow but useful authority

An active job alone does not prove that an index is globally unavailable. Incremental work can
retain a last-known-good generation, and a failed clean generation can remain unavailable
after its job terminates. A complete availability model therefore belongs to the service-owned
generation and publication state.

Active matching work does establish one narrower fact: an empty result is not authoritative
for the latest requested root and source while convergence is in progress. Returning a
temporary failure for that empty outcome closes issue 252 without claiming that every search
or every active job makes the service unavailable. Nonempty results can remain successful.

### Overlapping campaigns constrain the seam

Service-job-control is replacing the evictable compatibility ring with canonical job
resources. Large-index-resilience will add generation, publication, and
`rebuild_incomplete` fields to those resources. Both campaigns are actively editing
`src/vaultspec_rag/jobs.py`, and the job-control plan later edits the HTTP route.

This feature must not add a third registry, infer destructive state from progress text, or
modify the shared job module opportunistically. A route-local normalization seam may consume
copied current and canonical snapshots, with exact root and source matching. The complete
generation-aware classification remains sequenced after the resilience authority exists.

### Response options

- **HTTP 503 with the existing structured error envelope.** This gives generic HTTP clients a
  non-success signal and lets the shared client preserve a stable `ok: false` body. The CLI
  already takes the failure path when `results` is absent. The MCP adapter needs an explicit
  pre-validation guard because its output model currently defaults missing `results` to an
  empty list. Request for Comments (RFC) 9110 section 15.6.4 defines 503 for temporary inability to handle a
  request: https://www.rfc-editor.org/rfc/rfc9110.html#section-15.6.4.
- **HTTP 200 with `authoritative:false`.** This minimizes transport change but leaves generic
  automated consumers vulnerable when they ignore the optional field. It does not close the
  reported ambiguity at the HTTP boundary.
- **Hybrid availability.** Return 503 for non-authoritative empty outcomes and destructive or
  incomplete generations. Continue to return 200 for nonempty results and stable no-match
  outcomes. This closes the current bug and composes with later generation state.
- **409, 202, or 206.** These describe resource conflict, asynchronous acceptance, and range
  responses. They do not express temporary search-substrate unavailability as directly as
  503\.

No credible completion estimate exists, so the response should not invent a `Retry-After`
value. The current structured envelope is sufficient; adopting RFC 9457 problem details would
be a broader API migration.

### Regression boundary

The first executable artifact belongs in
`src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`. It should drive the
real service and build 256 well-formed synthetic vault documents with seed 252. It submits a
clean reindex, polls the returned exact job for at most 10 seconds, and sends the guaranteed
no-match query `type:nonexistent availability authority probe` once the job is running. The
raw request obtains its bearer token from `/health`, uses a 300-second deadline, and must
return the exact HTTP 503 envelope. The test then waits at most 300 seconds for successful job
completion and proves the same query returns the ordinary HTTP 200 empty response.

Timeout evidence includes `/health`, the exact `/jobs` response, `/metrics`, and the last
search response. Later assertions in the same real lifecycle cover unrelated roots, unrelated
sources, a useful nonempty result, the shared HTTP client, and the MCP adapter. Each assertion
is introduced by a distinct plan Step and commit. The test uses real Qdrant and GPU models
without fakes, mocks, patches, skips, expected failures, or mirrored business logic.

The immediate decision cannot close failed-clean-generation ambiguity until the resilience
campaign publishes destructive-generation state. That future evidence extends the 503 rule
only for otherwise-empty responses. Useful nonempty results remain HTTP 200 unless a later
architectural decision changes that policy. This dependency is explicit rather than hidden
behind counts or job heuristics.

## Sources

Evidence gap: the retained document body has no separately labelled Sources section.
