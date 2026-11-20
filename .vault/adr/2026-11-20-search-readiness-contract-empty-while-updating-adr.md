---
tags:
  - '#adr'
  - '#search-readiness-contract'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:94689f11f71b6c087dbe2f667a3605b857dc2d1adecee7ca07232cb9f055a9e7'
related:
  - "[[2026-09-08-search-readiness-contract-adr]]"
  - "[[2026-10-12-destructive-rebuild-lifecycle-adr]]"
  - '[[2026-09-08-search-readiness-contract-research]]'
  - '[[2026-09-08-search-readiness-contract-reference]]'
---

# `search-readiness-contract` adr: `return non-authoritative empty search results as success while an index job runs` | (**status:** `deprecated`)

## Problem Statement

Search refuses an empty answer whenever an index job is active for the requested root and source. The classifier marks the source `freshness=updating` and `absence_authority=non_authoritative`, then turns an empty result list into HTTP 503 `index_unavailable` with reason `index_updating` (`src/vaultspec_rag/server/_search_availability.py:562`, `src/vaultspec_rag/server/_search_route_availability.py:313`). Ordinary incremental and watcher jobs run often, so a caller sees an outage for a query that merely has no match. `2026-09-08-search-readiness-contract-adr` mandates this refusal ("Empty results are success only when the aggregate absence authority is authoritative"), and `2026-10-12-destructive-rebuild-lifecycle-adr` preserves it during a rebuild. The user wants search to stay available while indexing, with explicit partial or updating warnings.

## Considerations

- A usable collection that returns no hit has answered the query. Only the claim that nothing exists is unproven.
- The readiness fact already carries `availability`, `freshness`, `absence_authority`, `reason_code`, and bounded job evidence. A caller can branch on those without a failure status.
- A source that was never built, a missing collection, a rebuild-required refusal, a capacity refusal, and an unreachable backend cannot answer at all. Those differ from "no match yet".
- Adapters transport service-owned facts and must not derive their own verdict.

## Considered options

- **Keep the 503 refusal.** Rejected: it reports an outage for a working index and contradicts the user's search-while-indexing direction.
- **Return 200 with an explicit non-authoritative marker when a usable source has an active job.** Chosen: the answer is truthful, the absence claim stays non-authoritative, and every other refusal is unchanged.
- **Treat the prior published generation as authoritative during an incremental job.** Rejected: an incremental job can be removing or adding the very content the query targets, so absence cannot be certified.

## Constraints

Accepted 2026-11-20. Basis: User instructed on 2026-11-20 that every identified backlog issue, including search-while-indexing (empty results during a job return 200 with an updating/non-authoritative marker), lands in one PR.

Retired 2026-11-20 after the accepted amendment was applied to `2026-09-08-search-readiness-contract-adr` and reconciled in `2026-10-12-destructive-rebuild-lifecycle-adr`. Those records now carry the binding ruling; this record keeps the rationale and compatibility notes.

- An empty result is success when the source is `availability=usable` and an active index job matches its root and source (`freshness=updating`, reason `index_updating`). This covers incremental, watcher, and rebuild jobs. The response never claims authoritative absence.
- These cases keep their typed failures: a source that was never built (503 `index_unavailable`, reason `index_not_built`), a missing or vanished collection (503 `index_unavailable`), `rebuild_required` and `rebuild_refused` (409), a deleted root (410 `root_missing`), `capacity_limited` and `backend_unavailable` (503), a bounded freshness wait that times out (503 `freshness_wait_timeout`), and an empty unverifiable source with no active job (503 `index_unverifiable`).
- Nonempty results are unchanged: HTTP 200, marked `updating`.
- Combined search applies the same rule per constituent. An empty combined answer is success only when no constituent failed and every non-authoritative constituent is in the updating-usable case above. Otherwise it fails as before.
- No new wait, lock, poll, or retrieval change is introduced.

## Implementation

We will return HTTP 200 for an empty answer from a usable source with an active matching index job, and carry the marker in fields every adapter already transports:

- `results: []`.
- `readiness`: the source and aggregate blocks carry `availability=usable`, `freshness=updating`, `absence_authority=non_authoritative`, `reason_code=index_updating`, `retryable=true`, bounded job ids as `evidence`, and the jobs remediation.
- `empty`: `reason=index_updating`, a message saying absence is not established while the job runs, and the jobs command as remediation.
- `index_state`: `status` is `updating`, or `rebuilding` when a rebuild-mode job matches, plus bounded `matching_jobs` and `matching_jobs_truncated`.

The service decides this once, from one predicate on the source fact, for the single-source and combined paths. The HTTP status mapping, the service client, CLI JSON, and MCP structured content pass the envelope through unchanged. CLI human output already renders `empty.message`, `empty.remediation`, and the readiness line.

Client compatibility: a client that branched on `error == "index_unavailable"` with reason `index_updating` to detect indexing in progress now receives a success envelope. It must read `readiness.aggregate.absence_authority`, or `empty.reason`, instead. A client that treats every empty 200 as proof of absence must check `absence_authority` first. Every other failure code and status is unchanged.

## Rationale

The source can serve; only the absence claim is unproven, and the readiness fact already says so in a typed field. Making that a failure conflated "cannot answer" with "cannot prove absence" and made routine background indexing look like an outage. Keeping every true inability to answer as a typed failure preserves the refusal where it carries information.

## Consequences

Search stays available through incremental, watcher, and rebuild jobs, with an explicit non-authoritative marker on empty answers. Callers that need certified absence must check `absence_authority`, or use the bounded freshness policy, which still waits for publication. Operator logs record such searches as completed rather than unavailable.
