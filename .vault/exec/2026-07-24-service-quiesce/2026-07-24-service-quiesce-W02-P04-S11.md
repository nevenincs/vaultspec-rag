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

Unresolved. The earlier completion claim remains withdrawn.

## Description

The registry transition owner must keep the controller in `warming` with compute admission closed through GPU rebuild and durable same-ID recovery preparation. Recovery preparation persists eligible `paused` and `queued` jobs whose desired state is `running` before `complete_warming` opens the new admission epoch.

## Outcome

Pending: order resume as warming, rebuild, typed durable recovery preparation, controller acknowledgement, and dispatch. A recovery persistence failure must return `resume_recovery_failed`, retain `warming`, and remain admission-closed. A later resume must retry recovery instead of taking an unconditional already-running shortcut.

## Evidence

The accepted ADR now binds persistence-before-admission and typed fail-closed recovery. No implementation evidence currently satisfies this reopened Step.

## Notes

The registry transition condition owns serialization only; GPU and job-manager locks remain unnested. No service, RAG endpoint, CUDA allocation, or GPU test was run.
