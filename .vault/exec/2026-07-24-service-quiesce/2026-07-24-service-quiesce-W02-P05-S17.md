---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S17'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# CPU managed-job recovery proof remediation

## Status

Satisfied by the landed manager recovery implementation and its checked-in CPU proof. No test command was rerun during this release review.

## Description

Manager proof covers real unpublished-write rollback and retry, durable queued-state restart recovery, and an atomic exact-attempt dispatch claim across concurrent and loopless scheduling.

## Outcome

A pending recovery token binds the logical job ID, attempt, dispatcher binding nonce, and claim generation under the manager lock. Canonical dispatch consumes only that exact token; concurrent scans report one claimant, while cancellation, shutdown, missing or stopped loops, and later owner-loop recovery clear or supersede stale claims without creating another attempt. The manager tests retain one ID, increment the resumed attempt once, and dispatch once.

## Evidence

The checked-in tests use the production manager, real filesystem persistence, real threads, real event loops, and real runners. They cover unpublished failure and repaired retry, durable queued restart, concurrent claim coalescing, loopless dispatch through the adopted service loop, blocked callback invalidation, and recovery after missing or stopped loop ownership. Commit `b0d28a30` routes recovery through canonical manager dispatch rather than a second callback implementation.

## Notes

This closes the manager boundary only. Registry-owned persistence-before-admission and repaired concurrent retry are satisfied separately under S12 by `bbf02d53`. The independent loopless-callback finding was rejected during final acceptance: canonical admission consumes the exact claim before task creation, and every earlier refusal or loop handoff failure clears that exact claim, so the alleged retained pending claim has neither a valid source path nor a real reproducer. No speculative task-factory repair was committed. No service, RAG endpoint, CUDA allocation, GPU test, or CPU test was run in this reconciliation.
