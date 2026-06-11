---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S39'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Write the preprocessing-hooks user guide covering config, schema, and the command-only v1 security posture (D9, D13)

## Scope

- `docs/preprocessing-hooks.md`

## Description

Wrote `docs/preprocessing-hooks.md`: how the hook works, the `.vaultragpreprocess.toml` rule
format (pattern, command, priority, on_error, timeout_s, options), the `preprocess list/check/run-one` verbs, the versioned output schema with a worked JSON example,
caching/incremental behaviour, failure visibility, the emitted-size cap, and the
security posture (project-root trust, command-only v1, subprocess isolation) (D9, D13).

## Outcome

User-facing guide complete and linked from the README and configuration docs.

## Notes

States the v1 command-only limitation and the entry_point follow-up plainly.
