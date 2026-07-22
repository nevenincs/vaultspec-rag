---
tags:
  - '#adr'
  - '#search-index-availability'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-search-index-availability-research]]"
  - "[[2026-07-21-search-index-availability-reference]]"
  - "[[2026-06-11-search-freshness-and-empty-results-adr]]"
  - "[[2026-06-11-server-bound-search-production-readiness-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
---

# `search-index-availability` adr: `authoritative empty search responses during index work` | (**status:** `accepted`)

## Problem statement

Issue 252 establishes that an empty Hypertext Transfer Protocol (HTTP) `/search` response is
not authoritative when index
work for the exact resolved project root and requested source overlaps the request. Returning
HTTP 200 with zero rows in that interval is indistinguishable from a genuine no-match result
and manufactures false negatives for automated consumers.

The accepted empty-search decision requires operational state to distinguish no match from
unavailable or changing index state. The current route derives availability from collection
counts and does not close the race between retrieval and response emission.

## Terms

- An **authoritative empty response** is an HTTP 200 response whose empty `results` array may
  safely be interpreted as no match in the currently published index.
- A **convergence job** is an index operation bringing one project root and one source toward
  the files currently on disk.
- A **nonterminal convergence job** is a canonical index job in `queued`, `running`,
  `pausing`, `paused`, or `cancelling`, or a compatibility record in `running`.
- The **normalized source** is `vault` for the vault search branch and `code` for the code or
  codebase search branch.
- The **resolved root** is the request root returned by `_resolve_root`. Snapshot roots are
  expanded and resolved without requiring the path to exist, normalized with the host
  platform's path-case rules, and compared for equality. Prefix matches are forbidden.
- A **compatibility snapshot** has the legacy top-level `source`, `phase`, and
  `initiator.project_root` fields. A **canonical snapshot** has `spec`, `state`, and `id`.
- **Stable** means neither observation contains a matching nonterminal convergence job. It
  does not claim that future generation-ledger evidence is available.
- GPU means graphics processing unit. CI means continuous integration.

## Considerations

- A zero count can mean a missing index, collection replacement, or an ordinary empty corpus.
- A positive count during rebuilding does not prove completeness. Early committed batches can
  expose a partial collection.
- Matching must use the canonical resolved project root and normalized requested source. Jobs
  for other roots or sources do not affect the response.
- Nonempty results remain useful during overlapping work and must remain HTTP 200.
- Index work can begin or finish while retrieval runs. One preflight observation cannot
  establish the authority of a later empty result.
- Current compatibility job snapshots expose enough root, source, and nonterminal-state evidence
  for a narrow guard, but they are not the final lifecycle authority.
- Canonical job control and the large-index generation ledger are accepted but still in
  flight.
- Existing clients recognize structured failures through `ok: false`. The 503 body must omit
  `results` so no client can reinterpret the response as a successful empty search.
- Indexing progress provides no credible completion estimate.

## Considered options

- **Keep HTTP 200 and add an availability field.** Rejected: generic and existing consumers
  can continue treating an empty `results` list as authoritative success.
- **Reject every search while any index job is nonterminal.** Rejected: unrelated jobs must not
  reduce availability, and nonempty results from the requested index remain useful.
- **Check convergence work only before retrieval.** Rejected: index work can begin after the check
  and produce an empty response from a changing collection.
- **Wait exclusively for the generation ledger.** Rejected as the immediate remedy: issue 252
  needs protection now, while the ledger remains the future complete authority.
- **Double-observe matching convergence work and reject only empty results.** Chosen: this closes
  the known response race narrowly, preserves useful nonempty results, and composes with the
  canonical state that later campaigns will expose.
- **Publish every rebuild through a shadow collection.** Deferred by the large-index-resilience
  decision because it changes storage and publication architecture and increases peak storage.

## Constraints

- Matching uses exact canonical project-root and requested-source identity. Path-prefix,
  display-string, cross-root, and cross-source matches are invalid.
- The service captures a copied job snapshot before retrieval and rechecks convergence work
  before emitting an empty success.
- If matching nonterminal work was observed before retrieval or at the response boundary, an empty
  result is non-authoritative.
- The failure response is HTTP 503 with `ok: false`, `error: "index_unavailable"`, no
  `results` member, the exact envelope in the HTTP response contract, and no undeclared
  success fields.
- `index_state.status` is `updating` unless canonical evidence proves a rebuild, in which case
  it is `rebuilding`. Compatibility snapshots must not infer rebuilding from prose, counts,
  or request intent.
- Nonempty results remain HTTP 200 even when matching index work overlaps the request.
- Empty results remain HTTP 200 when no matching nonterminal work overlaps the request. Unrelated
  jobs are ignored.
- `Retry-After` is omitted unless the service later owns a credible completion estimate.
- The narrow guard may consume compatibility snapshots but must not introduce another job
  registry, duplicate lifecycle state, or require changes to `jobs.py`.
- The accepted June empty-search decision remains stable. This decision extends its HTTP
  authority semantics and does not supersede it.
- Service-job-control remains the canonical lifecycle direction. Large-index-resilience
  remains the canonical generation and publication direction.
- When the generation ledger exposes `rebuild_incomplete` for a destructive generation, the
  same HTTP 503 rule persists for an otherwise-empty response until valid publication, even
  if no nonterminal job remains. This decision never converts a nonempty result to 503.
- Tests use production routes, real job execution, real storage, and real models without
  fakes, mocks, stubs, patches, monkeypatching, skips, or expected failures. GPU acceptance
  runs locally because no GPU CI runner exists.
- The shared HTTP client preserves the daemon body. The Model Context Protocol (MCP) adapter
  raises a recoverable tool error for any structured search body with `ok: false` before
  `SearchResults` validation, so its default `results` field cannot manufacture an empty
  success.

## Implementation

### Snapshot classification

The service normalizes a copied snapshot with this precedence and predicate:

| Shape         | Required identity                                                                                                                                                     | Convergence predicate                                                | Rebuild evidence                 |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | -------------------------------- |
| Canonical     | Nonempty `id`; `spec.operation` is `index`; `spec.source` equals the normalized source; normalized `spec.project_root` equals the resolved root                       | `state` is `queued`, `running`, `pausing`, `paused`, or `cancelling` | `spec.mode` is exactly `rebuild` |
| Compatibility | Used only when the `spec` key is absent; nonempty `id`; top-level `source` equals the normalized source; normalized `initiator.project_root` equals the resolved root | `phase` is exactly `running`                                         | Never; exposed mode is `null`    |

If the `spec` key exists, the record is canonical. Canonical fields are authoritative. A
non-mapping or malformed `spec` record is ignored rather than reclassified through
compatibility fields. Terminal canonical states,
including `failed` and `cancelled`, and terminal compatibility phases do not match. Resource
flags and progress text never override observed state. Future generation state owns failures
that outlive a job.

Canonical mode normalization is closed: exact `rebuild` remains `rebuild`, exact
`incremental` remains `incremental`, and a missing, null, non-string, or unrecognized value
becomes `null`. Only normalized `rebuild` contributes rebuilding evidence.

Each observation consumes the complete service-owned copied snapshot. The registry already
bounds that snapshot. Response evidence is separately capped at eight unique jobs. The second
observation comes first, followed by jobs seen only in the first observation. The stable `id`
deduplicates the list, so the second observation's state wins. Availability status is computed
from every unique match before response truncation. `matching_jobs_truncated` is true when
more than eight unique matches existed.

### HTTP response contract

Search retrieval proceeds normally. A nonempty result keeps the existing HTTP 200 success
contract. Before an empty success is emitted, the service performs the second observation. If
either observation matched, it discards the success envelope and emits exactly these declared
fields. The existing index count and target fields come from `_search_index_state`:

```json
{
  "ok": false,
  "error": "index_unavailable",
  "message": "The vault index for C:\\work\\project is changing; this empty search cannot establish that no matches exist.",
  "request_id": "0123456789abcdef0123456789abcdef",
  "index_state": {
    "source": "vault",
    "indexed_count": 42,
    "indexed_target_root": "C:\\work\\project",
    "requested_target_root": "C:\\work\\project",
    "target_matches": true,
    "status": "rebuilding",
    "matching_jobs": [
      {
        "id": "fedcba9876543210fedcba9876543210",
        "state": "running",
        "mode": "rebuild"
      }
    ],
    "matching_jobs_truncated": false
  },
  "remediation": [
    "vaultspec-rag server jobs --state active --index vault --port 8766",
    "Retry the search after the matching index job reaches a terminal state."
  ]
}
```

`status` is `rebuilding` when any unique canonical match before truncation has mode `rebuild`; otherwise
it is `updating`. Each job reference has exactly `id`, `state`, and `mode`. `mode` is
`incremental`, `rebuild`, or `null`. The message substitutes the normalized source and
resolved root. The port suffix is present in HTTP service mode. No `results`, `summary`,
`empty`, or `timing` member is emitted. No `Retry-After` header is sent.

When neither observation matches, the ordinary empty-result contract remains HTTP 200. It
continues to distinguish a missing index from an available index with no match. The helper
reads service-owned snapshots but never extends their schema, changes `jobs.py`, or owns a
registry.

The MCP search adapters inspect the structured daemon body before Pydantic validation. Any
body with `ok: false` raises an actionable `RuntimeError` containing the daemon error code,
message, and remediation. FastMCP maps that recoverable exception to `isError: true`. Valid
search envelopes continue through `SearchResults` unchanged. The regression invokes the real
MCP stdio shim through the official client and asserts `CallToolResult.isError is True`. Its
text contains `index_unavailable` and the jobs command, and its structured content is absent
or has no `results` member.

### Deterministic regression handshake

The regression uses the function-scoped real subprocess service and the existing synthetic
corpus builder to create 256 well-formed vault documents with seed 252. It submits a real
clean vault reindex, retains the returned job ID, and polls authenticated `/jobs` every 50
milliseconds for at most 10 seconds. The compatibility handshake requires `phase: running`
and a `progress.step` other than `queued`. The canonical handshake requires `state: running`
and `resources.project_lease_held: true`. These conditions prove the real indexer entered
under the project lease before searches are admitted. The search query is
`type:nonexistent availability authority probe`, an existing
production filter behavior that guarantees no matching document without mirroring search
logic in the test.

After the running-state handshake, a real thread executor admits every probe concurrently.
This is required because production searches may wait for the project lease until indexing
finishes; each route must capture its first observation before that wait. The final probe set
contains raw matching-empty, unrelated-root-empty, unrelated-source-empty, and
matching-nonempty HTTP requests, plus the shared-client and MCP matching-empty calls. The
matching nonempty query uses a known needle from the generated corpus. No test double or
production mutation controls the timing.

Each request uses a 300-second deadline. Raw HTTP requests use the bearer token read from
`/health`. The primary root is the 256-document corpus. The unrelated root is a second empty
project containing only `.vault`. The unrelated-source probe searches code in the primary
root with `include_paths: ["__availability_no_match__/**"]`. The matching nonempty probe uses
the first corpus manifest needle. Both shared-client and MCP probes use the guaranteed
matching-empty query and the primary root.

The HTTP 503 assertion requires the exact declared key sets. Dynamic fields are checked by
contract: `request_id` is 32 lowercase hexadecimal characters, `indexed_count` is a
nonnegative integer from the real search, roots equal their resolved strings, and the returned
job reference contains the submitted job ID. The current compatibility snapshot reports
`status: updating`, `state: running`, and `mode: null`; a canonical rebuild reports
`status: rebuilding`, `state: running`, and `mode: rebuild`.

The concurrent assertion matrix is:

| Probe                           | Request                                                                                     | Expected result                                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Raw matching empty              | Primary root, `vault`, guaranteed no-match query                                            | HTTP 503; exact failure key sets and dynamic predicates; submitted job reference; no `results`     |
| Raw unrelated root              | Empty secondary root, `vault`, guaranteed no-match query                                    | HTTP 200 with `results: []`                                                                        |
| Raw unrelated source            | Primary root, `code`, ordinary query plus `include_paths: ["__availability_no_match__/**"]` | HTTP 200 with `results: []`                                                                        |
| Raw matching nonempty           | Primary root, `vault`, first manifest needle                                                | HTTP 200 with at least one result containing that needle's document identity                       |
| Shared client matching empty    | Primary root, `vault`, guaranteed no-match query                                            | Dictionary with `ok: false`, `error: index_unavailable`, submitted job reference, and no `results` |
| MCP matching empty              | Real stdio `search_vault` call for primary root and guaranteed no-match query               | `CallToolResult.isError is True`; actionable text; no structured `results`                         |
| Post-convergence matching empty | Primary root, `vault`, same guaranteed no-match query                                       | HTTP 200 with `results: []` and `empty.reason: no_match`                                           |

The test asserts every independent contract after all futures settle. It polls the same job
every 100 milliseconds for at most 300 seconds until compatibility `phase: done` or canonical
`state: succeeded`. Any failure or cancellation fails the test with the job result and error
evidence. It then repeats the raw matching-empty query and asserts the ordinary HTTP 200 empty
contract. Timeout failures include the latest `/health`, exact `/jobs`, `/metrics`, and
response evidence. Later test Steps append one probe at a time to this one
service-and-job lifecycle; each invariant remains a separate commit.

When large-index-resilience publishes `rebuild_incomplete` for a destructive generation, it
becomes an additional reason to apply this same contract to an otherwise-empty response. A
future change that blocks nonempty results requires its own architectural decision record.

## Rationale

The chosen guard protects the only currently ambiguous outcome: an empty result whose
authority is undermined by overlapping index work. It preserves useful search availability,
avoids broad rejection caused by unrelated activity, and observes both sides of retrieval so
a single stale preflight check cannot manufacture success.

HTTP 503 communicates temporary inability to answer authoritatively to generic HTTP
consumers. The structured body preserves the project's machine-readable service contract.
Omitting `results` prevents compatibility clients from collapsing the failure back into an
empty-success path.

Using current snapshots only as a compatibility input avoids competing with
service-job-control. Deferring complete publication authority to the large-index generation
ledger preserves its ownership of durable `rebuild_incomplete` state, including failures that
outlive their active job.

## Consequences

- Automated consumers can distinguish authoritative no-match from temporary index
  unavailability through both HTTP and structured service semantics.
- Searches returning real rows remain available during indexing.
- Unrelated project or source work has no effect on search outcomes.
- Empty searches overlapping even non-destructive work return a conservative 503 until
  stronger generation evidence can prove authority.
- Each potentially empty search performs two bounded job-state observations.
- Compatibility logic must be replaced by canonical job and generation views as their
  campaigns land, without changing the external 503 contract.
- A failed clean rebuild remains unavailable after its job terminates once
  `rebuild_incomplete` generation state is exposed.
- Clients that assumed every `/search` response contained `results` must handle the existing
  structured failure convention.
- Retry timing remains client-controlled until the service can provide a defensible estimate.
