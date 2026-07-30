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

Unresolved. The earlier completion claim is withdrawn.

## Description

The prior CPU proof covers successful same-ID resume but not recovery persistence failure, partial durable publication, restart recovery, or duplicate-attempt prevention.

## Outcome

Pending: use the real manager, production persistence writer, real filesystem failure, and real async dispatch to prove unpublished-write failure stays closed and retries; separately restore a real durably queued desired-running generation to prove post-publication restart recovery. Both paths must preserve one logical ID, increment the attempt only once, dispatch once, and leave desired paused or cancelled work untouched.

## Evidence

No current test satisfies both observable persistence outcomes without fakes, mocks, patches, monkeypatches, skips, or xfails.

## Notes

All required proof is CPU-only. No service process, RAG endpoint, CUDA allocation, or GPU test was run.
