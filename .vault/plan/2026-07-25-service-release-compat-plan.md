---
tags:
  - '#plan'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
tier: L1
related:
  - '[[2026-07-25-service-release-compat-adr]]'
---

# `service-release-compat` plan

- [x] `S01` - Add the shared release-compatibility module owning the verdict type, the wire field name, and the cached local-release lookup; `src/vaultspec_rag/serviceclient/_release.py`.
- [x] `S02` - Enforce the discovery discriminator at both readers, refusing an unrecognised shape and resolving a live holder's foreign pointer as degraded; `src/vaultspec_rag/serviceclient/_discovery.py`.
- [x] `S03` - Publish the package release on the health route, the readiness report, the daemon discovery snapshot, and the launcher status write; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `S04` - Adapt the start and status verbs to render the shared verdict without gating, keeping the attach path a zero-exit success; `src/vaultspec_rag/cli/_service_start.py`.
- [ ] `S05` - Add the compatibility test module, mutation-prove all three guards, and reconcile the two exact-key-set assertions the new field grows; `src/vaultspec_rag/tests/test_service_release_compat.py`.
- [x] `S06` - Document the enforced pin and the release field in the service discovery reference; `docs/service-discovery.md`.

## Description

## Steps

## Parallelization

## Verification
