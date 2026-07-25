---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S15'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Render the survey verdict and stamped models in the storage CLI view

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

## Outcome

The storage CLI carries `models` in its JSON, and in the human view names a
namespace whose collections disagree with each other plus a count of namespaces
that predate stamping.

Deliberately bounded, per the operator-views rule. A per-namespace model line
would add noise to every row to state the expected case; only a namespace
holding more than one distinct model gets a line, because collections under one
root disagreeing about what built them is the state worth attention. The
unstamped count is a single trailing line rather than a marker per row.

## Notes
