---
tags:
  - '#adr'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-index-completeness-guard-research]]"
  - "[[2026-07-25-index-resume-drift-race-adr]]"
---

# `index-completeness-guard` adr: `reconcile published evidence against stored breadth and refuse silent partial answers` | (**status:** `accepted`)

## Problem Statement

A code index can latch into a state where it holds a small fraction of the
corpus while reporting itself complete, and search answers confidently over that
fraction. `2026-07-25-index-completeness-guard-research` establishes the
mechanism: a clean rebuild drops the collection before repopulating it, an
incremental run can escalate itself into that clean path without operator
action, a failure part-way leaves the fragment, and the metadata sidecar still
describes the whole corpus. Every later incremental run diffs against that
metadata, concludes nothing changed, and publishes success. The index never
heals.

The guard written for exactly this failure,
`src/vaultspec_rag/indexer/_codebase_indexer.py:1647`, asks whether the
collection *exists* rather than whether it holds what the metadata *claims*, so
a partially destroyed collection passes it. Because a clean rebuild drops and
then incrementally repopulates, every interrupted clean rebuild lands in the
undefended middle between intact and absent - the common case is the unguarded
one.

A decision is needed because the harm is not retrieval quality but a false
negative to "does this already exist?", which is the question the mandated
grounding step asks before code is written.

## Considerations

- The count search reports and the vectors search ranks come from the same live
  collection (`src/vaultspec_rag/store.py:1663`, `src/vaultspec_rag/api.py:605`),
  so no reporting fix can surface this; the deficit is only visible against a
  record of what was *published*.
- The metadata sidecar already carries non-file bookkeeping keys
  (`__code_embed_schema__`, `__code_membership_epoch__`, `__code_content_epoch__`,
  `__code_generation_id__`), so it is an established home for a published-breadth
  fact and needs no new artifact.
- Enumerating distinct payload paths costs a full scroll of the collection.
  Paying that on every incremental run is not acceptable, and payload indexes are
  ignored in local mode, so a facet-based distinct count is not portable across
  backends.
- `count_code` is already called on the search path, so a count-based
  completeness check adds no store round trip there.
- A legitimate shrink (files deleted) travels the incremental path, which
  republishes metadata. An unexplained shortfall against the published figure is
  therefore genuinely anomalous rather than routine drift.
- Full reconciliation is failure-safe (`clean=False`): a false escalation costs
  GPU time, not data. The asymmetry favours escalating on doubt.
- No reconciliation is instantaneous, so a legitimately incomplete window will
  always exist. Silence during that window is a separate defect from the latch
  and is not fixed by fixing the latch.
- Health, status, and diagnostics belong to the service domain with CLI and MCP
  adapting, so the completeness fact must be computed once below the adapters.
- Existing sidecars carry no published-breadth key; an upgrade must not force a
  rebuild on every root.
- The indexed-path upsert collision that aborts runs is owned separately by
  `2026-07-25-index-resume-drift-race-adr`. That work reduces how often runs
  abort; it does not change what an aborted run leaves behind.

## Considered options

**Compare stored distinct paths against the claimed file set.** The most direct
apples-to-apples comparison, and the measurement that diagnosed the defect.
Rejected as the runtime predicate because it requires a full scroll on every
incremental run and has no portable cheap form across local and server backends.
It remains the right shape for an offline audit.

**Persist the published point count and compare it against a live count.**
Cheap (one `count`, already paid on the search path), precise about the quantity
that was actually published, portable across backends, and stored in an existing
sidecar. Chosen.

**Make clean publication non-destructive (build into a shadow collection, swap
atomically).** Strictly better: it removes the truncation window rather than
detecting it. Deferred, not rejected - it touches the storage layer and the
per-root collection-prefix scheme, needs disk headroom for a duplicate
collection on a machine already tight on storage, and is not required to stop the
silent false negative. Recorded as follow-up.

**Search-time signal only.** Stops the silence but leaves the index truncated
until a human runs a rebuild. Insufficient alone; adopted as one half of the
chosen pair.

## Constraints

- The completeness fact is computed once in the service domain; CLI and MCP
  adapt to it and never recompute or reinterpret it.
- The predicate must add no store round trip to the search path beyond the count
  already taken there.
- A sidecar with no published-breadth key keeps today's existence-only behaviour;
  absence is not treated as a shortfall.
- Escalation targets the failure-safe reconciliation path, never a destructive
  clean rebuild - the fix must not be able to cause the data loss it prevents.
- Guard tests prove they can fail: the forbidden state is made permissible, the
  test observed failing for its intended reason, restored, and observed passing,
  with both directions recorded.
- No development metadata in source, tests, comments, or docstrings.

## Implementation

**Publish breadth.** At code-index metadata publication, record the point count
and file count the run actually published as reserved sidecar keys alongside the
existing `__code_*` bookkeeping.

**Quantitative predicate.** Replace the existence-only check at
`src/vaultspec_rag/indexer/_codebase_indexer.py:1647` with one that treats
carried evidence as unmet when the live point count falls short of the published
figure, retaining the absent-collection case it already covers. A shortfall
escalates to failure-safe full reconciliation, so a latched index heals on its
next scheduled run instead of persisting until a human intervenes.

**Completeness signal.** Expose the published-versus-live comparison as a
service-domain fact on the code search path, carried on the result envelope
alongside `indexed_count`. The CLI renders a warning naming the shortfall and the
remedy; MCP carries the same field. A search over a demonstrably incomplete index
can no longer present itself as authoritative.

**Audit path.** Keep the distinct-path-versus-claimed-files comparison available
as an operator check for confirming a suspected latch without a rebuild.

## Rationale

The defect is a predicate asking a binary question about a quantitative risk, so
the fix is to make the predicate quantitative. Persisting what was published is
what makes the comparison possible at all: with only live state, a truncated
collection is indistinguishable from a small one, which is precisely why the
failure was invisible.

Pairing the predicate with a search-time signal reflects that the two failures
are independent. Healing the latch removes the permanent case; the signal covers
every transient case, including a reconcile that is queued, running, or has just
failed again. Either alone leaves a window in which the tool lies by omission.

Deferring build-then-swap is a scope judgement, not a disagreement: it is the
better fix and is recorded as such, but detection restores trust in the index
now, and a non-destructive publication can land on top of a working completeness
fact later.

## Consequences

- A latched index self-heals on its next scheduled run rather than requiring a
  hand-run rebuild, at the cost of an occasional failure-safe reconciliation when
  the count legitimately disagrees.
- Search over an incomplete index becomes visibly incomplete. Callers that
  treated a confident empty answer as proof of absence must read the warning; the
  grounding step gains a signal it never had.
- The sidecar gains reserved keys. Roots written by an older build have none and
  keep existing behaviour until their next publication, so no forced rebuild.
- The truncation window itself remains until non-destructive clean publication
  lands; until then the signal, not the absence of the window, is what protects
  the caller.
- Storage-layer atomic publication is queued as follow-up work.
