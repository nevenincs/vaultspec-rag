---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:1fb272d4ef8a17d4fbff4df33a1d0662f658797565a1fc6f33b1093120396286'
step_id: 'S12'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Integration-test that reconcile against a real server reclaims measured bytes, preserves exact point counts, and leaves dense search results identical

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`

## Description

- Add `test_reconcile_reclaims_bytes_and_preserves_data`, `test_reconcile_is_idempotent_on_a_converged_backend`, `test_reconcile_dry_run_changes_nothing`, and `test_reconcile_cap_defers_remaining_collections` to `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`.
- Add helpers that build a collection carrying the pre-bound geometry with dense and sparse vectors and production-style payload indexes.
- Set `default_segment_number` explicitly rather than leaving it at the server default.
- Assert measured byte reclamation, exact point preservation, and identical dense search results across five fixed probe queries.

## Outcome

Reconciliation is proven against a real qdrant server to reclaim measured bytes while preserving every point and leaving dense search results unchanged, and to be idempotent, inert under dry-run, and correctly capped. The explicit segment number keeps the test modelling the same drift on any host, since the server default derives from host CPU count.

## Notes

No incidents.
