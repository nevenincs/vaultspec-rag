---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:d0b1b181e3f001ffa70d02f67b45ecdc68c112a31a152a0d2cd355b6c4be8aff'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# `storage-autoprune-safety` `P01` summary

All four Steps complete (S01 manifest grace clock, S02 reclamation
engine, S03 config knobs, S04 unit tests), one commit per Step plus a
review follow-up.

- Modified: `src/vaultspec_rag/storage_manifest.py`
- Modified: `src/vaultspec_rag/storage_ops.py`
- Modified: `src/vaultspec_rag/config.py`
- Created: `src/vaultspec_rag/tests/test_storage_ops.py`

## Description

The time-confirmed danglingness contract: `first_seen_orphaned` persists
in the manifest (restart-proof, reset on reappearance, lenient
pre-upgrade load), `evaluate_reclaim` stacks the safety gates
(orphaned-only, per-tier grace, riskless-empty-first under the per-cycle
cap), `archive_prefix` snapshot-archives point-bearing namespaces
fail-closed before any drop, `sweep_archive` bounds the archive tree by
age and total bytes, and `run_maintenance_cycle` orchestrates one
auditable pass through the shared `delete_prefix`. Seven
`storage_autoprune*` knobs (hourly default, 24h/168h grace tiers, 30-day
20GB archive bounds, 16-per-cycle cap). Review follow-up added a
pre-drop point re-count on the archiveless empty tier. Verification: 15
new unit tests plus the full storage/manifest suites green; audit passed
with data safety explicitly confirmed non-bypassable and fail-closed.
