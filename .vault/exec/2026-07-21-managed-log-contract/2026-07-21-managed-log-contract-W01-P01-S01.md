---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:7fae48f7e8ad620bd7d18213c9fc96270be43bdc81831c5dc725f2c598f4c45c'
step_id: 'S01'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Replace service-only retention settings and environment names with the generic managed-log contract

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Rename the retention fields and environment bindings to the generic managed-log contract.
- Validate positive byte limits and non-negative backup counts.
- Remove the service-only configuration names without aliases.

## Outcome

Service and Qdrant logging now consume one clean-break retention policy with 10 MiB and five-backup defaults.

## Notes

No compatibility path was retained, as required by the accepted ADR.
