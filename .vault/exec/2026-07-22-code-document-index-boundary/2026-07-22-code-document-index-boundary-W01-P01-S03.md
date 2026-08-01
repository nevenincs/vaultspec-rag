---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:e885010b99eb5343f371c35c30f349103f56ef6192717b07088d7e518073314b'
step_id: 'S03'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Upgrade preprocessing configuration to require a target and explicit extractor version under a versioned schema

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

- Advance the preprocessing schema major to version 2.
- Preserve missing top-level versions as legacy version 1.
- Require a closed target content kind on every transform rule.
- Require an explicit caller-managed extractor version on every transform rule.
- Preserve schema identity across spawn-worker pickling.
- Validate lint, typing, imports, and real version-2 TOML loading.

## Outcome

Preprocessing rules now carry explicit ownership and extractor identity under a versioned,
picklable schema. Legacy policy remains distinguishable for S04 migration refusal.

## Notes

No incidents or data loss. Fail-closed entry-point gating and structured migration errors are
deliberately deferred to S04.
