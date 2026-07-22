---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S47'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Derive per-kind membership and content signatures from source profile, ordered routes, targets, ignores, schema, and extractor semantics

## Scope

- `src/vaultspec_rag/indexer/_config_epoch.py`
- `src/vaultspec_rag/indexer/_resolved_policy.py`

## Description

- Derive closed code and document fingerprint projections from one policy snapshot.
- Include source profile, ordered routes, ignores, transform targets, and schema in membership.
- Keep operation-only excludes separate from persistent membership identity.
- Filter extractor semantics by target so content rebuilds remain kind-local.
- Include decoder, parser, raw-chunk, transform, and byte-cap semantics in content identity.
- Keep execution mode outside per-kind membership and content identities.
- Validate extractor changes, target flips, profile changes, excludes, and closed kind lookup.

## Outcome

Code and document consumers now receive independent membership and content identities from
the same immutable snapshot. Ownership moves invalidate both affected memberships, while a
kind-local extractor change cannot force an unrelated kind's content rebuild.

## Notes

No incidents or data loss. Durable generation/checkpoint binding is scheduled for later plan
steps; S47 supplies the normalized per-kind signatures required by that work.
