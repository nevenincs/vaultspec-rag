---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:92bed8ffa08b8f7b4467bfa848948ea7044f36e339911e38e06121833510e9bf'
step_id: 'S06'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# add a fragment discriminator to the location component so it applies to both the locator and unit-ordinal identity branches

## Scope

- `src/vaultspec_rag/indexer/_document_identity.py`

## Description

- Add a `fragment_ordinal` parameter to `document_point_id` and fold it into the `location` component for BOTH identity branches in `src/vaultspec_rag/indexer/_document_identity.py`.
- Validate the fragment ordinal as a non-negative non-bool integer, mirroring the unit ordinal's validation.

## Outcome

A locator-bearing unit's identity ignores the unit ordinal, so only a location-level discriminator prevents fragment collisions; ids are unique by construction on both branches.

## Notes

The discriminator is included unconditionally (fragment 0 too); replay stability comes from deterministic emit order plus the version bump, not from omitting the zero case.
