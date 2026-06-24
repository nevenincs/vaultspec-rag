---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S12'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Add orientation and debug intent weight profiles and the per-type cap to config

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Added three env-overridable scalar knobs to `_RAG_DEFAULTS` and `EnvVar`/`_ENV_OVERRIDE_MAP`:
  `vault_intent_default` (orientation), `vault_intent_ranking_enabled` (True), and
  `vault_intent_type_cap` (4).
- Added the `_INTENT_WEIGHT_PROFILES` ClassVar carrying the orientation and debug
  per-(type, status) multiplier matrices, with an `intent_weight_profiles` read-only
  property, so the weights are config-resident, inspectable, and sweepable.

## Outcome

Config exposes the operational knobs and the weight profiles. Verified: default intent
orientation, cap 4, ranking enabled; orientation adr=1.0/exec=0.4/superseded=0.3; debug
exec=1.0/adr=0.6. `ruff` and `ty` pass.

## Notes

The full multiplier matrices live as a class constant rather than per-cell env vars (a matrix
is impractical to env-override); the scalar operational knobs remain env-tunable. Only the
orientation and debug profiles ship, matching the ADR's two-profile decision. No blockers.
