---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:b9da1b25a8cb520bf55497d259eff9409476a28f78a336f01757fcadaaabaf43'
step_id: 'S09'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Exercise the maintenance cycle end to end against a live service with a short interval: an aged empty orphan is reclaimed, a fresh orphan waits, a reappearing root resets its clock, and the cycle appears in server jobs

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_maintenance.py`

## Description

- Add `test_storage_maintenance.py`: a real daemon on a seconds-scale
  interval, three real staged namespaces in its managed qdrant and its own
  manifest. Asserts the aged empty orphan is reclaimed and forgotten by
  the manifest, the fresh orphan waits out its window, the reappearing
  root's grace clock clears and its data survives, and every cycle is a
  finished `source=maintenance trigger=schedule` job with a rollup
  summary. Determinism: assertions only run against cycles whose
  `started_at` postdates the staging; root dirs exist at spawn so the
  startup manifest reconcile keeps their entries; the aged backdate uses
  a verified clear-then-set (the stamp helper deliberately preserves an
  existing stamp).
- Fix the two bugs the first live run caught: the interval default is now
  a float (env coercion is default-type-driven, so `int` rejected the
  fractional-minute test seam), and the loop's failure path gained a
  60-second backoff await - a pre-sleep exception previously recurred
  with no await point, pinning the event loop and starving every request
  handler (the daemon answered nothing, including `/health`).

## Outcome

1/1 passing live in 41.6s; config suite still green (45); ruff and
basedpyright clean.

## Notes

The never-yield busy loop was exactly the failure class the ADR's
crash-proof-loop constraint exists for; the backoff is now part of the
loop's contract.
