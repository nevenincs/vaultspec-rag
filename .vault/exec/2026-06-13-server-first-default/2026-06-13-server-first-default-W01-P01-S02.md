---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S02'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add the LOCAL_ONLY env var member and its \_ENV_OVERRIDE_MAP entry so a single knob selects the local backend across config resolution

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Added a `LOCAL_ONLY` member to the `EnvVar` enum bound to `VAULTSPEC_RAG_LOCAL_ONLY`, so the local-backend opt-out has a single canonical env-var name alongside the other supervised-qdrant knobs.
- Added a `local_only` entry to `_ENV_OVERRIDE_MAP` pointing at `EnvVar.LOCAL_ONLY`, so once the matching default exists the env var participates in the wrapper's standard resolution chain.

## Outcome

The local-only knob now has its env-var name and override-map wiring in place. The map entry is inert on its own: `__getattr__` only routes a key through `_resolve_rag_default` (and therefore the override map) when that key is present in `_RAG_DEFAULTS`, which `local_only` is not until the next Step. This Step deliberately lands the naming and map plumbing without behaviour, matching the plan's Step split. `ruff check` and `basedpyright` on the changed source are clean.

## Notes

No behaviour change is observable yet; the default and the effective-mode resolution that activate this knob land in S03, and the asserting tests in S04.
