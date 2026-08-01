---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:368a718fe237fbe9b65f01d52fe58527bf0859bd954b73e816fafef612625fab'
step_id: 'S06'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Resolve one immutable policy snapshot containing routing, preprocessing, decoding, execution mode, and normalized fingerprints

## Scope

- `src/vaultspec_rag/indexer/_resolved_policy.py`
- `src/vaultspec_rag/indexer/_config_epoch.py`

## Description

- Resolve routing, ignores, transforms, decoding, and execution mode once per operation.
- Freeze preprocess options recursively into typed, picklable canonical values.
- Rebuild derived ignore and transform matchers from immutable tuple authority.
- Separate persistent and operation-only membership identities.
- Version policy, parser, chunk, decoder, transform, content, and execution semantics.
- Compile raw caller routes into closed target and source-profile vocabularies.
- Validate static checks, route behavior, identity boundaries, and pickle reconstruction.

## Outcome

`ResolvedIndexPolicy` now provides one reconstructible value for discovery, worker,
fingerprint, checkpoint, and publication consumers. Execution-mode changes retain ownership,
operation-only excludes do not contaminate persistent epochs, and mutable option materialized
for a worker cannot mutate the active snapshot.

## Notes

No incidents or data loss. Entry-point gating and exact snapshot threading remain scheduled
for S88 and S90; S06 establishes the immutable authority they will consume.
