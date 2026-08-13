---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:7be0ea0e8075b4d1fb63e2c261bda4f55a85ee4913ded3e06988e8967eb9ee8c'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
---

# `large-index-resilience` audit: `ledger concurrency`

## Scope

Mandatory review of the durable-state concurrency work: write-ahead logging on the shared per-root ledger, integrity verification moved off the open path, handle-scoped connections, contention as a typed retryable outcome, and the accompanying concurrency coverage. Reviewed at high effort against the branch diff and the working tree, with the SQLite behaviour claims checked empirically rather than by reasoning.

## Findings

Three high-severity findings, all confirmed and all fixed. Each was a case of the change appearing correct in isolation while the surrounding system undid it.

**The typed kind was never consulted.** Contention classified correctly but was absent from the watcher's retryable set, and the watcher opens its circuit on anything outside that set. One contention failure therefore paused automatic indexing on first occurrence - byte-for-byte the outcome the old unclassified path produced. The classification work had achieved nothing at the boundary that matters. Fixed by adding the kind to that set, and guarded by asserting the retry decision rather than the label.

**A held lock was reported as corruption, twice.** Opening the ledger and verifying its integrity both convert database errors into a corruption error, and a lock error is a database error. Opening now converts the journal mode and schema-migrates, so a peer's transaction can block it - meaning every existing installation's first concurrent open after this change could be reported as corrupt durable state, unrecoverably. The verification case was worse: it runs on the resume path precisely when a generation carries storage-confirmed work, so it would discard exactly what the change exists to protect. Both paths now separate contention out ahead of the conversion.

Two medium findings were also fixed. The journal-mode readback treated a contended first answer as the filesystem's verdict, permanently failing a root over a condition lasting milliseconds; it now retries briefly before judging. The contention replay covered only one write path while the adjacent per-file writes on the same hot path went through bare transactions; they now share one composed helper rather than gaining wrappers each.

A low finding on compounding budgets was fixed by sizing the busy budget against the replay budget: the worst case had exceeded the deadline at which a job without a progress tick reads as degraded, so one contended write could have flipped a healthy run to degraded. A low finding on the source-level guard covering only two of the six durable-state modules - omitting the one the contract was actually lost in - was fixed by widening the scan.

The review separately confirmed several things clear: the migration journal's schema creation autocommits, so moving it off the committing context manager loses nothing; the replay arithmetic is correct; and the client cap matches the pinned server version.

## Recommendations

All high and medium findings are resolved in this branch; no follow-up is outstanding against this work.

The pattern worth carrying forward is that every one of the high findings sat in the gap between a change and the system around it. Classification was correct but unconsulted; error translation was correct but sat beneath a handler that flattened it. Neither would have been caught by testing the changed unit, and neither was caught by a green suite. A durable-state change should be traced to the boundary that consumes its outcome - the retry decision, the circuit, the error conversion - rather than verified where it was written.

The binary-pin question is left open deliberately. The locked client had moved a minor line ahead of the reviewed server pin; capping the client restores the invariant without minting new binary digests. Raising the pin instead is a security-boundary change requiring six reviewed per-platform digests, and is an owner's decision rather than an incidental one.
