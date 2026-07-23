---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S35'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Render checkpoint, retry, circuit, memory, profile, and remediation fields without recomputing policy

## Scope

- `src/vaultspec_rag/cli/_service_jobs.py`

## Description

- Confirm the CLI job render emits the checkpoint, retry, circuit, memory,
  profile, and remediation fields from the recorded snapshot
  (`src/vaultspec_rag/cli/_service_jobs.py:843`).
- Confirm the render derives remediation from the recorded outcome and
  recomputes no policy (`src/vaultspec_rag/cli/_service_jobs.py:294`).

## Outcome

The CLI renders every resilience field this step names, derives remediation from
the recorded outcome, and recomputes no policy to do it. The render was already
committed ahead of this plan's execute phase, so this record confirms it against
the contract.

The render covers the full set: the support profile, the checkpoint generation
and its compatibility, the committed and resumed unit counts, the no-progress
budget remaining, the retry circuit state and next-retry time, the RSS and CUDA
high-water against their ceilings, and the terminal index outcome. Each reads
from the resilience block on the job record.

Two properties beyond mere coverage hold. Remediation is derived, not stored:
the render classifies the recorded outcome text and looks up the shared operator
remediation for it, so the action an operator sees comes from the same source
the API response and the typed error use, never a second copy. And the render
recomputes no policy - it names no policy resolver, no configuration read, no
snapshot machinery - so it reflects exactly the state the job recorded rather
than re-deriving a fresh and possibly divergent view at display time. That is
what lets the CLI, the API response, and the health rollup agree: all three
read one recorded snapshot rather than each measuring its own.

## Notes

Verified and recorded, not executed here - the render was committed before this
plan's execute phase reached the step. The coverage and the no-policy-recompute
property were confirmed by reading the render and its imports: it pulls the
shared remediation helper and names no policy resolver or configuration read.

The remediation helper it shares is the same one the response shaping now uses,
so an operator reading a failed job on the CLI and a broker reading the same job
over the API receive the same recommended action, derived once from the recorded
outcome rather than authored twice.
