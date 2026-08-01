---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
body_hash: 'sha256:46991ebeec7856eb58b311c4e3dc044eba4b24ce745458c52b38f8ee66577a3d'
step_id: 'S11'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Implement a service-domain survey function that enumerates namespaces, joins the manifest, and classifies live, orphaned, and unknown

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Add classify_namespaces: group stored collections by r{hash}\_ prefix, join the manifest, label live/orphaned/unknown, aggregate counts/footprint, sort actionable-first.

## Outcome

Pure classification core; 5 unit tests cover all three states and aggregation. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.
