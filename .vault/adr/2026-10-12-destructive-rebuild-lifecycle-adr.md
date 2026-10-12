---
tags:
  - "#adr"
  - "#destructive-rebuild-lifecycle"
date: '2026-10-12'
related:
  - "[[2026-10-12-destructive-rebuild-lifecycle-reference]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-09-08-search-readiness-contract-adr]]"
  - "[[2026-09-08-incremental-publication-cost-adr]]"
  - "[[2026-09-01-generation-accounting-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
  - "[[2026-07-25-index-lifecycle-consolidation-adr]]"
  - "[[2026-05-30-cli-index-default-adr]]"
  - "[[2026-07-25-storage-conformance-adr]]"
supersedes:
  - '2026-07-25-non-destructive-index-publication-adr'
modified: '2026-10-12'
body_schema: 'body-v2'
body_hash: 'sha256:2897818750f413aa4ab218ebdf37b8b4592566ba7992e27de371a1de4a11e311'
---

# `destructive-rebuild-lifecycle` adr: `discard the old index and search the new build as it grows` | (**status:** `accepted`)

## Problem Statement

An explicit rebuild currently preserves the index it was requested to discard. Code builds a second collection and switches at completion; vault and documents replace live points in place. Old code generations then remain for maintenance. These differences complicate storage, recovery, and search semantics without expressing different user intent.

The user directs one architecture: rebuilding discards the selected old index and constructs it again, while the service continues processing indexing and search queries. The source evidence and existing seams are recorded in `2026-10-12-destructive-rebuild-lifecycle-reference`.

## Considerations

- The user explicitly rejects retaining the old search index during or after a rebuild and explicitly requires concurrent indexing and search.
- A partial new index can answer useful searches without proving corpus completeness or authoritative absence.
- A reset must invalidate old completeness claims and prevent old writers or cached readers from reintroducing discarded state.
- Code, vault, and documents differ in admission and payloads, not in what rebuild means.
- The existing hard-delete path verifies local deletion, so a new collection name per rebuild is no longer required merely to avoid local point resurrection.
- Durable units permit restart and pause without retaining the pre-rebuild index. A new rebuild and resuming the same rebuild are different operations.

## Considered options

- **Keep the old index and swap a completed replacement.** Rejected: contradicts the requested discard semantics, duplicates index storage, and requires pointer and retention machinery.
- **Overwrite the old index and purge at the end.** Rejected: retains old content throughout ingestion and gives different domains different reset semantics.
- **Delete and block search until completion.** Rejected: contradicts the requirement to serve searches while rebuilding.
- **Delete first, build one live collection, and search its fresh partial contents.** Chosen for code, vault, and documents with one shared lifecycle and source-specific producers.

## Constraints

Accepted 2026-10-12 under the user's explicit instruction to revise the architecture to discard the old index on rebuild, unify all domains, and continue serving indexing and search concurrently. This acceptance authorizes the architecture revision; it does not assert runtime implementation or authorize an operational reset of existing indexes.

### Authority and selected scope

A new explicit rebuild resets only the selected canonical root, backend, and source domains. Every public full-index operation has this meaning. Adapters must not reinterpret `full`, `clean`, or rebuild authority as preservation. CLI rebuild still requires an explicit source selection under `2026-05-30-cli-index-default-adr`. Ordinary incremental operations retain their bounded update semantics and cannot escalate to a rebuild. Existing MCP incremental tools do not gain destructive authority.

Admission validates the request, policy, backend ownership, and required resources before destructive work. A queued or refused job has not yet reset anything. Once an admitted rebuild enters reset, old data is discarded before any new corpus ingestion. The operation creates no backup, shadow copy, retained old generation, or deferred grace-period deletion. This is explicit operator-authorized index reset; automatic orphan maintenance keeps its separate safeguards.

`all` selects all three domains and reports their independent outcomes. It does not promise a cross-domain transaction or roll back a completed domain when another fails. A single-domain rebuild must not reset sibling collections, their evidence, extraction caches, or unrelated roots.

### One lifecycle, one live index

A single source-neutral rebuild coordinator owns reset, current epoch, recovery, and completion. Domain adapters supply admitted inputs, chunking/extraction, payloads, and domain-specific counts. The existing shared event wrapper remains the event owner; it does not grow a second job registry or duplicate publication authority.

Each selected domain has one canonical live collection derived from its root and source kind. Rebuild deletes the prior collection, verifies deletion, recreates it empty, and writes directly into it. Logical generation IDs remain durable run identities, not names for retained parallel collections. Source-specific geometry does not change reset semantics.

The lifecycle persists reset intent and retires old publication authority before deletion. It proves the target is empty before admitting replacement writes. Storage handles, ensure/conformance latches, code pointer bindings, and result/graph caches bound to discarded data are invalidated at the same boundary. No old checkpoint or publication proof may seed the new run. The shared ledger is reset by selected source and backend, never by deleting another source's database state.

### Search and indexing remain concurrent

Search capacity and indexing capacity remain independent. No job-wide reader lock, whole-rebuild search refusal, global quiesce, second GPU model stack, or second indexing GPU consumer is introduced. Local point-operation locks may serialize individual calls; neither backend may serialize searches behind the whole build. GPU locking remains confined to forward passes, with bounded scheduling that gives both indexing and searches progress.

During the brief reset operation, the selected source may return a typed retryable `index_transition` outcome or perform an already-bounded transition retry. It must not wait for the full rebuild. Other sources continue serving. Readers capture and validate the current reset epoch around retrieval and before returning results; a read crossing reset cannot return old-generation results after the reset boundary. Old writer attempts are drained or fenced before deletion and cannot write into the replacement after it opens.

Once the empty replacement is ready, search addresses it throughout ingestion. Fresh points become searchable as bounded writes are applied; search never waits for final publication to expose them. Nonempty results carry `availability=usable`, `freshness=updating`, and `absence_authority=non_authoritative` until completeness is certified. The service exposes the current serving generation separately from the last completed publication. Open receipts prevent a claim of completeness, not useful retrieval from a compatible current epoch.

An empty result while rebuilding cannot prove no match in the complete corpus. Preserve the existing structured non-authoritative outcome, with rebuild state and retry information, instead of calling it authoritative empty success. Once a genuinely empty corpus is fully rebuilt and verified, empty success becomes authoritative. Combined search retains the readiness and partial outcomes of every selected source; adapters transport the same service-owned facts.

Default immediate searches do not wait for completion. An explicitly requested bounded freshness wait still waits for certified completion of its captured target and obeys its own deadline. Paused, failed, or cancelled builds retain searchable new points with explicit incomplete state; retryability and remediation reflect the actual job state, not an invented completion estimate. A physical storage or model-compatibility failure can still make a source unavailable.

### Durability and completion

Reset is a durable, replayable phase of the existing run ledger, keyed by root, backend, source, and rebuild generation. Persist intent and invalidate old proof, delete and verify, recreate and verify empty, then record reset completion before any ingestion. Recovery before reset completion repeats that idempotent phase; recovery afterward preserves only storage-confirmed work from this rebuild. Backend identity, schema, model, and policy compatibility remain mandatory.

A new rebuild request starts a fresh generation and resets again. Idempotent replay of an existing request, resume, linked retry, and daemon recovery retain their explicitly bound rebuild generation and do not reset confirmed new progress. They cannot resume a superseded generation after another rebuild has replaced it. Ordinary incremental work for the same source waits or refuses while an incomplete rebuild owns mutation authority; watcher events continue to accumulate for later reconciliation.

Pause and cancellation protect only reset and indivisible mutation/commit boundaries. After the empty target is ready, they can acknowledge at durable unit boundaries and release execution resources. A partial new index is an intentional served state, not a reason to defer control until the full corpus finishes. Crashes and failures never restore or fall back to the discarded old index.

Finalization verifies storage application, exact source membership, required outcomes, model/schema identity, and durable evidence before marking the current generation complete. It changes the completeness claim on the same live collection; there is no collection swap. Expected partial growth is never compared with the discarded generation's counts and never schedules automatic full repair. Existing resource ceilings, bounded writes, and no-progress deadlines remain enforced.

### Prior decision coverage

This decision supersedes `2026-07-25-non-destructive-index-publication-adr` in full. Its explicit-authority, storage-before-proof, single-GPU, and bounded-operation protections are retained by the contracts above and the related authorities; its shadow collections, pointer-last swap, duplicate-storage admission, and old-generation retention are removed.

Scoped amendments accompany this decision in `2026-09-07-explicit-reindex-authority-adr`, `2026-09-01-generation-accounting-adr`, and `2026-09-08-incremental-publication-cost-adr`: reset-first rebuild and progressive search replace preservation and pointer-last clauses. Complete-proof certification remains fenced, while current-epoch partial reads do not require a completed proof.

`2026-09-08-search-readiness-contract-adr` is refined to distinguish a fresh partial serving generation from complete publication. `2026-07-21-large-index-resilience-adr` and `2026-07-21-service-job-control-adr` are amended to bound the protected reset interval rather than protecting an entire rebuild. `2026-07-25-index-lifecycle-consolidation-adr` keeps event ownership and gains the shared rebuild coordinator alongside it. `2026-07-25-storage-conformance-adr` no longer assumes rebuild preserves mixed old/new vectors. Content-kind isolation and backend-aware concurrency remain binding.

## Implementation

We will route explicit code, vault, and document rebuilds through one reset-first lifecycle, backed by the canonical source-partitioned ledger and existing verified hard-delete primitive. Storage preparation, checkpoint recovery, search generation evidence, and final proof publication must ship together.

At the first explicit rebuild of a selected source, enumerate and verify ownership of its existing canonical and historical generation collections. Remove those indexes and obsolete served-pointer/retention state as part of that reset, before ingestion. Do not copy old payloads or use old proof to seed replacement. Unknown or foreign names are refused, not swept by a broad prefix deletion. Existing unselected indexes continue through their established read path until explicitly reset; discovery alone grants no deletion authority.

Use the existing hard-delete implementation for local handle closure and disk verification as well as server deletion. A residual local directory or failed backend delete is a reset failure; recreation must not silently resurrect points. Canonical collection naming removes generation-pointer publication after cutover. Historical layout recognition is limited to exact reset ownership and existing unselected reads; it is not a fallback writer or a permanent alternative rebuild strategy.

Extend the existing publication/readiness authority to carry reset epoch, serving generation, applied progress, and completeness as separate fields. A reader of incomplete compatible storage may return useful current-epoch results without certifying absence. Final publication continues to require all receipt and apply barriers. Never disable integrity checks globally to enable partial search.

The plan `2026-10-12-destructive-rebuild-lifecycle-plan` sequences implementation and the cross-domain acceptance matrix. Exact helper names and schema representation are implementation choices within this contract. This architecture revision does not claim runtime rollout.

## Rationale

Discarding the old index and searching the replacement during ingestion satisfies both explicit user requirements. Keeping only one live index removes the duplicate-storage and old-generation reclamation costs inherent in the rejected design. A common lifecycle eliminates the current semantic split without merging the distinct content producers.

The evidence in `2026-10-12-destructive-rebuild-lifecycle-reference` identifies existing reset, ledger, and readiness owners. Reusing them preserves durability and resource discipline while correcting their preservation assumptions. Completeness belongs to final verification; useful search does not require pretending that verification has already happened.

## Consequences

A rebuild immediately loses the old index once reset executes. Search coverage starts empty and grows as replacement writes apply; there is no old-index fallback on failure. Returned matches can be useful while missing matches remain non-authoritative. Pause and recovery preserve the new partial index, and a separate new rebuild discards it again.

Disk use no longer includes an intentionally retained predecessor plus replacement. Logical generations and proof history may remain as bounded job evidence, but cannot retain old searchable payloads or old collections. Native storage reclamation still follows confirmed backend deletion rather than promising instantaneous operating-system space recovery.

Implementation must revise reader epochs and completeness projection together with all three producers, including adapters and caches. Guard tests must fail when old content survives reset, partial new results are blocked until completion, stale writers cross reset, or incomplete evidence is advertised as complete. Acceptance of this decision records the requested architecture; completion of its implementation plan establishes delivery.
