---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:f3434ad4b644b9f954ca941fa04f3a5108a9ae9729f68f53ab91ee1ff1ae750c'
step_id: 'S16'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Gate watcher dispatch through persistent circuit transitions

## Scope

- `src/vaultspec_rag/watcher.py`
- `src/vaultspec_rag/server/_watcher.py`
- `src/vaultspec_rag/tests/test_watcher_unit.py`
- `src/vaultspec_rag/tests/integration/test_watcher_config.py`

## Description

- Separate filesystem-event collection from the indexing dispatcher so new
  intent is durably generation-marked while an indexing call is in progress.
- Coalesce wakeups and pending paths without retrying on every idle tick.
- Retain observed paths and retry failed intent persistence asynchronously;
  never dispatch or discard the batch before its generation is durable.
- Refresh both durable source states on every idle dispatch check so a retiring
  watcher cannot strand intent behind a replacement's cached clean view.
- Admit closed work and one due half-open probe through the persistent policy.
- Settle every admitted attempt on success, failure, or cancellation.
- Preserve unknown restart scope as an unscoped convergence pass.
- Retry transient policy construction during replacement startup instead of
  allowing a contended state lock to make the watcher disappear.
- Remove naturally exited watcher tasks from the server's running registry.

## Outcome

The one-second watcher idle tick no longer creates an unbounded failure storm.
Pending work remains coalesced behind the persisted retry deadline, and only a
due transition may dispatch. Events received during an active attempt advance a
durable generation before the older attempt can settle; that newer generation
therefore remains pending for another pass. Cancellation releases the claim
without misclassifying an operator stop as an indexing failure. A transient
state-lock timeout no longer terminates the collector, loses the batch, or
stalls unrelated service requests on synchronous lock polling. Admission and
terminal settlement are cancellation-shielded until their state transition is
durable; a cancellation racing admission cannot leave a live-process orphan.
If the main state lock remains unavailable, bounded cancellation writes a
separate durable recovery marker so shutdown completes and a replacement owns
the convergence obligation. Mixed vault/code batches settle both source
obligations before deferred cancellation is delivered. Abandonable native
state transactions use four non-blocking worker slots, preventing repeated
cancellation from creating an unbounded set of stalled filesystem threads. Two
independent bounded handoff slots reserve recovery-marker capacity even when all
ordinary state workers are stalled.

Watcher classification now shares the indexer's extension authority and
normalizes suffix case. A malformed retry state fails closed, and the server
removes the exited task instead of reporting it as running indefinitely.

## Notes

The existing job-recording calls remain the watcher-facing job surface in this
phase. Consolidation onto the accepted canonical durable job manager and direct
watcher circuit observability remain later plan ownership; this step does not
add a second compatibility path.
