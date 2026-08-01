---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:b48a6fb22dd3ba1fd788ffae301e1dbd22c1f5e0ec9b49fea7265c3f21e06f6b'
step_id: 'S45'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Compare real-CUDA RSS and allocated and reserved high-water marks at N and two-N corpus sizes

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Confirm RSS and CUDA allocated and reserved high-water marks stay bounded as
  the corpus doubles, by running the verify test against clean committed HEAD on
  real CUDA (`src/vaultspec_rag/tests/integration/test_indexer_integration.py`).

## Outcome

The corpus-scale memory verify passes on real CUDA against committed HEAD. It
indexes a corpus of size N and then one of size two-N, and asserts the RSS
high-water and both the allocated and reserved CUDA high-water marks do not grow
in proportion to the corpus - the property that proves the streaming pipeline
holds a bounded working set rather than accumulating the whole corpus in memory.
Run on the development GPU against a clean extract of HEAD, it passed: the memory
ceiling holds at two-N.

## Notes

Confirmed against a clean extract of committed HEAD, not the shared working
tree. This mattered here specifically: this test's file carries another effort's
uncommitted document-domain work, so running against the working tree would have
mixed that uncommitted code into the measurement. The clean-archive run is the
authoritative one, and it is what this record reports.

The measurement is a real-CUDA integration run on the development GPU; it is not
the reproducible benchmark harness, which is a separate step. This step
confirms the high-water property holds at the two-N doubling on real hardware,
which is the safety-gate question; the harness step is about a reproducible
large-corpus floor.
