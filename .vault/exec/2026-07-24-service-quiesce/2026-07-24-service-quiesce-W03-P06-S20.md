---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e3bbfdece3c0f0c1450adb492135ffb06569920446b35ee1d0aaaf40a946f232'
step_id: 'S20'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Publish the canonical quiesce block through existing health, jobs, and lifecycle heartbeat cadence without adding a poller, duplicating controller computation, or importing GPU dependencies

## Scope

- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/server/_routes.py`

## Description

Project the current canonical controller envelope through the existing health
and jobs request cadence. Read one registry snapshot for each response and
reuse `QuiesceSnapshot.as_envelope` without a new poller or local lifecycle
recomputation.

## Outcome

Satisfied jointly by `04660476` and `9fc85828`. Health and jobs now publish the
same twelve-field quiesce block directly from the registry controller.
Checked-in CPU route guards cover running, quiesced, and resumed observations.

## Notes

The implementation adds no GPU dependency and no lifecycle polling loop. This
was static acceptance only; no runtime or static gate was rerun.
