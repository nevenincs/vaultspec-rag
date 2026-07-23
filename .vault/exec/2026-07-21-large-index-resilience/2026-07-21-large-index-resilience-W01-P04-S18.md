---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S18'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify low RSS and CUDA ceilings stop production with typed outcomes and bounded cleanup

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Confirm low RSS and low CUDA ceilings stop production with typed outcomes and
  a released pipeline, by running both verify tests against clean committed HEAD
  on real CUDA (`src/vaultspec_rag/tests/integration/test_indexer_integration.py`).

## Outcome

Both memory-ceiling verifies pass on real CUDA against committed HEAD. A low RSS
ceiling and a low CUDA ceiling each stop production with the typed outcome for
that ceiling, the recorded high-water exceeds the configured limit, the store
holds no points from the aborted run, and the pipeline is released. Run on the
development GPU against a clean extract of HEAD, both passed.

## Notes

This step's honest history includes a wrong first result, recorded here because
the correction is the useful part. An initial run was made against the shared
working tree without first checking its state. That tree carried another
effort's uncommitted work in this exact test file - a document-domain parity
suite plus a change to the CUDA-ceiling test's own assertion - and the modified
assertion failed, so the run reported a CUDA-ceiling failure. A fix was drafted
against that contaminated assertion before the contamination was noticed.

The error was caught by extracting committed HEAD to a clean location and
running the test there: HEAD passes. The drafted fix was then reverted precisely
\- restoring the file to the other effort's uncommitted state without a
checkout that would have destroyed their work - and the authoritative result is
the clean-HEAD run, which passes for both ceilings. The lesson taken, and now a
standing practice for this plan's verifies, is to check the working tree's state
and run against a clean archive before trusting a verify result on a tree shared
by several efforts.

The document-domain parity suite in this file is a separate inherited feature,
not part of this step and not this author's work; it is left untouched for its
owner to review and land with its supporting code.
