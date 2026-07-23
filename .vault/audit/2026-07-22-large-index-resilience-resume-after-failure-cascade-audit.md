---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` audit: `self-perpetuating incremental index failure on resumed generations`

## Scope

An operational failure observed on the resident service during live use, not a test finding. Over a twenty-minute window every watcher-triggered code index update failed, six consecutively, while vault indexing continued to succeed. The investigation traced the raise sites, attributed the change that introduced them, and established whether the failures were independent or a single cascading condition.

The observation matters because it was invisible to the test suite. Every gate was green while the running service could not index code at all, and the condition is self-perpetuating rather than transient, so it does not clear on its own.

## Findings

### resume-after-failure-cascade | high | A failed incremental index job leaves a resumable generation that every later job inherits and re-fails, permanently

The run ledger refuses an upsert commit unit for a path already recorded as indexed within the same generation. That guard is generation-scoped and it is correct - it is catching a genuine inconsistency rather than being over-strict.

The defect is upstream of it, in which generations are eligible for resumption. Starting a generation resumes any existing one whose signature matches and whose terminal state is resumable, and the resumable set includes failed, cancelled, running, and rebuild-incomplete states while excluding only succeeded. A job that succeeds therefore retires its generation and the next job starts clean, which is why normal operation shows no symptom. A job that fails leaves its generation resumable, carrying every file state it had already marked indexed.

From that point the failure is self-sustaining. Each subsequent watcher job shares the signature and resumes the same failed generation. Any path that was already marked indexed and has since been edited presents a different source digest, and because unit identity incorporates the source digest, the incoming unit is a new identity for an already-indexed path. Deduplication cannot suppress it by construction. The guard fires, the job fails, the generation remains failed and resumable, and the next job repeats the sequence.

The observed trigger was benign and unrelated: a single job failed because an admitted source file produced no chunks, the classic outcome of reading a file mid-save on an actively edited tree. That first failure is inconsistent state and needs no fix. Everything after it is the cascade, and the distinction is visible in the errors themselves - the first failure carries a different message from the five that follow it.

The condition is not recoverable by waiting. A full rebuild clears it, but only until the next failed incremental job is followed by an edit to any file that job had already indexed. In a watcher-driven workflow against a live working tree, a file changing between attempts is the normal case rather than an edge case, so recurrence is expected rather than unlikely.

Attribution is established: both raise sites arrive from commits that are ancestors of the current head and are dated the same day the failures appeared, which is why the condition surfaced now and had never been seen before. It is not attributable to the concurrent boundary work, whose files do not reach admission or the ledger, nor to the unfinished effort's staged changes, whose hunks touch only memory budgeting and out-of-memory latching and whose added checkpoint calls raise pause or cancel signals without writing ledger state.

## Recommendations

Fix the resume path, not the guard. The guard correctly refuses an inconsistent write and loosening it would convert a visible failure into silent index corruption, which is strictly worse.

When resuming a generation for an incremental attempt, a path whose current source digest no longer matches the digest recorded when that path was marked indexed must be re-opened rather than refused: its state reset and its prior units superseded, so the path is indexed afresh within the resumed generation. That makes resume-after-failure robust to the source changing between attempts, which is the actual operating condition of a watcher-driven indexer.

Two further questions the implementing work should settle rather than assume. First, whether a failed generation should remain resumable indefinitely, or whether repeated failure against the same signature should retire it and force a clean start - an unbounded retry against a poisoned generation is the mechanism that turned one transient failure into a permanent outage. Second, whether the transient trigger deserves its own treatment: a source file that reads as empty mid-save is a foreseeable race on a live tree, and failing the whole job on it may be harsher than re-queuing that path.

Regression coverage must reproduce the cascade rather than the guard: fail an incremental job, edit a file that job had already indexed, run again, and assert the second attempt succeeds. A test that only asserts the guard fires would have passed throughout this incident.
