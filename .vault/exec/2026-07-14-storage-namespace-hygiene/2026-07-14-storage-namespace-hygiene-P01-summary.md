---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# `storage-namespace-hygiene` `P01` summary

Steps S01-S07 complete (S07 closed on the live integration run). Commit 7ae79ca plus the audit-driven doc note.

- Modified: `src/vaultspec_rag/server/_state.py`, `src/vaultspec_rag/server/_lifecycle.py`, `src/vaultspec_rag/server/_lifespan.py`, `src/vaultspec_rag/server/_routes.py`, `src/vaultspec_rag/server/__init__.py`, `src/vaultspec_rag/storage_ops.py`, `src/vaultspec_rag/serviceclient/_transport.py`, `src/vaultspec_rag/cli/_service_storage.py`, `src/vaultspec_rag/tests/test_storage_ops.py`, `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`

## Description

Made `/storage/survey` O(1) at any namespace count. The daemon holds one immutable `SurveySnapshot` (atomic reference swap in `_state`); it is published by a one-shot startup warmer (~5s after lifespan start, cold-slot-only), by every maintenance cycle (whose survey was previously discarded - `MaintenanceResult` now carries it, minus just-reclaimed prefixes), and by every fresh compute. The route serves the snapshot with filters applied post-cache and stamps `computed_at`/`source`; `?fresh=true` (CLI `--fresh`, forwarded through the transport) recomputes and reseeds. Verified by 8 new unit tests (including a cache-hit-does-zero-IO proof) and 3 live-daemon integration tests; the indexed-root lookup test now uses `fresh=true`, matching the ADR's eventual-consistency contract. All static gates green; reviewer verdict PASS (concurrency, staleness, and inertness explicitly clean).
