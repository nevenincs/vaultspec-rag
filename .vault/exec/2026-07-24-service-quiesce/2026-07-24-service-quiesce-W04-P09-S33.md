---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-31'
body_schema: 'body-v1'
step_id: 'S33'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---
# Route self-hosted CI and Just GPU tiers through S32's guarded coordinator only, remove direct GPU preflight and Qdrant installation, and declare the compatible resident service plus runner Qdrant binary and manifest as external prerequisites

## Scope

- `.github/workflows/ci.yml`
- `justfile`

## Description

- Commit `af6e1292` replaced the direct CI preflight and Qdrant installation steps with one `just test gpu` coordinator route.
- Kept the runner image as the owner of the pinned manifest-verified Qdrant prerequisite.
- Made the Just GPU and performance recipes invoke pytest only; they never provision Qdrant, preflight a GPU, or start a service.

## Outcome

Actionlint and diff checks passed. Static review found one CI coordinator route and no direct provisioning or preflight bypass.

## Notes

The live self-hosted GPU tier is delegated to its authorized maintenance window and was not run in this review.
