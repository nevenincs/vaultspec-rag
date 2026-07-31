---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S11'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---
# Registry transition coordinator remediation

## Status

Satisfied by the landed W02 implementation and reconciled source inspection. No runtime or test command was executed during this release review.

## Description

The registry transition owner keeps the controller in `warming` with compute admission closed through GPU rebuild and durable same-ID recovery preparation. Recovery preparation returns exhaustive typed evidence for `durable`, `not_required`, `unpublished`, and `published_not_durable` outcomes before `complete_warming` may open the new admission epoch.

## Outcome

`ServiceRegistry._resume_resources_once` opens admission only for prepared or no-work results. Unpublished rollback and published-but-not-durable retention map to distinct failure reasons under the one `resume_recovery_failed` transition, remain in `warming`, and schedule no work. A later resume retries the same paused-plus-queued scan.

## Evidence

Source inspection of the landed resume-recovery model and registry coordinator confirms exhaustive enum matching and distinct controller failure truth. The manager dispatch repair in `b0d28a30` does not supply this ordering by itself; the governing implementation is the typed recovery work landed earlier and retained at current HEAD.

## Notes

The registry transition condition owns serialization only; GPU and job-manager locks remain unnested. Public route-envelope rendering remains W03 work. No service, RAG endpoint, CUDA allocation, GPU test, or CPU test was run in this reconciliation.
