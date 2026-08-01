---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:c10d6ff1e964fc74d71341d0aba8d5ae53c70e1070d23f33d1c9cb739c2a8bbd'
step_id: 'S46'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Prove concurrent search retains reserved GPU headroom while bounded indexing progresses

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`

## Description

- Confirm concurrent search retains its reserved GPU headroom while bounded
  indexing progresses, by running the verify test against clean committed HEAD
  on real CUDA
  (`src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`).

## Outcome

The concurrent-headroom verify passes on real CUDA against committed HEAD.
While a bounded index job progresses, a concurrent search completes and the
search path retains its reserved GPU headroom rather than being starved by the
indexer - the property that keeps the multi-tenant service responsive under load
instead of letting a large index monopolise the device. Run on the development
GPU against a clean extract of HEAD, it passed: search keeps its reserved
headroom while indexing runs.

## Notes

Confirmed against a clean extract of committed HEAD. This test's file is not
among the ones another effort has uncommitted changes in, but it was still run
from a clean archive to hold one standard across this phase's verifies after an
earlier run in the phase was contaminated by the shared tree.

This is the last of the corpus-scale safety verifies. It is a real-CUDA
integration run, the slowest in the set - a concurrent search racing a bounded
index on real hardware - and it completed cleanly. It is distinct from the
reproducible benchmark harness, which is a separate step about a large-corpus
floor rather than the concurrent-headroom property confirmed here.
