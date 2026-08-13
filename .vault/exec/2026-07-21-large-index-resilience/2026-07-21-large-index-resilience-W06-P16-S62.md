---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:8bf95d3f35e299e50af900ed4951d80f7a8f67bdd52deafffea4a4afda950396'
step_id: 'S62'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Move full-database integrity verification off the per-run open path onto an explicit maintenance and recovery entry point

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`

## Description

- Remove the full-database integrity scan from the ledger's open path.
- Expose it as an explicit verification entry point on the ledger.
- Call it from the shared resume path in `src/vaultspec_rag/indexer/_checkpoint_common.py`, but only when the generation already carries committed units.

## Outcome

Opening the ledger no longer reads every page of a file shared by every content kind on the root. That scan was the long read that starved commits: its cost tracked total ledger size and it held a read lock throughout, so it grew worst exactly where resilience matters most.

Detection is not weakened, and the placement is deliberate rather than merely cheaper. Opening still reads the schema catalogue and the schema contract, and SQLite raises on a malformed image as soon as a query touches it - the existing fail-closed corruption cases all still pass. The deep scan now runs at the one moment durable state is about to be trusted to skip storage work, which is where undetected damage would actually cost something. A fresh run pays nothing.

## Notes

Removing the scan from the open path narrows what opening detects: page-level damage in an otherwise-openable file no longer surfaces there. That is why the verification entry point was wired to the resume path in the same change rather than left for a caller to remember - dropping a check without replacing it would have traded one defect for another.
