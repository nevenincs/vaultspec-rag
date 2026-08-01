---
tags:
  - '#exec'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:e4269480ea4da8922d702fb4cd89627b150b7bd21359b5efe9847eeadb84264a'
step_id: 'S01'
related:
  - "[[2026-07-23-cli-startup-feedback-plan]]"
---

# Carry a structured startup-progress descriptor (stage id, label, optional done/total) on the discovery snapshot and \_DiscoveryPublisher, additive and best-effort

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Added optional `phase_done`/`phase_total` parameters to `_daemon_discovery_snapshot`, included in the published fields only when a total is set.
- Added `phase_done`/`phase_total` state to `_DiscoveryPublisher` and accepted `done`/`total` on `publish_phase`, threaded into the snapshot.

## Outcome

The publisher and discovery snapshot carry an optional determinate count. A stage with a total stamps `phase_done`/`phase_total`; a countless stage omits both keys entirely, so no bogus `0/0` reaches a consumer. Additive and advisory: the coarse `phase` stays authoritative and no discovery-schema version bump was needed.

## Notes

Verified by the round-trip unit test in `S05`; no schema bump.
