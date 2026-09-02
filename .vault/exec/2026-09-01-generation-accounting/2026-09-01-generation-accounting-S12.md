---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:c77393858ed6b56d0721a4247ad59de37b3cac076e055fc1e43cbedc2d129637'
step_id: 'S12'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Prove clean-generation publication never reconciles the served collection early

## Scope

- `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`

## Description

- Seed a real stale point in the prior served code collection and an exact-evidence replacement in the private build collection.
- Route the replacement path to code while seeding its previous document owner, then publish through the production lifecycle.
- Assert the old served code stays whole, the replacement breadth is exact, and the document origin is removed only once the replacement is served.

## Changes

- Extended the local-store document seed helper with an explicit source-path input.
- Added a clean-generation publication regression with stale served code, a routed replacement, and a cross-kind document origin.

## Outcome

The regression covers the clean-generation publication boundary without a mock or a test-only production path. Static formatting, lint, `ty`, and strict basedpyright gates pass. The selected integration test is fail-closed before collection because no compatible resident machine-pointer service is available to this checkout.

## Notes

The focused runtime command stopped before test collection with the repository GPU/service guard; it was not bypassed. The guard demonstration remains documented beside the exact assertions: restoring pre-swap route reconciliation deletes the old served code and cannot retire the still-private replacement's document origin.
