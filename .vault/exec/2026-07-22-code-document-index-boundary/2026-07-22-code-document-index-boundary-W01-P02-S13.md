---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:32c50e048290944e32b1a45fdf18a91a2fd95b06ab2b6ba5778474a1184dd7ca'
step_id: 'S13'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Make resident-service preflight consume the structured scan without independently reloading configuration

## Scope

- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/server/_routes.py`

## Description

- Resolve resident-service code admission before durable job creation.
- Carry the exact policy and structured scan into job activation.
- Project admission and preprocessing status from that preflight without reloading config.

## Outcome

Resident-service preflight, response shaping, and index execution share one immutable policy
snapshot and structured scan.

## Notes

Reconciled from the landed service preflight implementation; no additional code change was
required.
