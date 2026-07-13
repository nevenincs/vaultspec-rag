---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S07'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Enforce the mode in load_preprocess_rules after resolution: off returns empty, trust_all returns rules with a loud log, and default returns rules only on a trust-record hash match else empty plus a loud actionable warning naming the preprocess trust verb, with the loader and worker never prompting

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

- Remove the old blanket pre-parse security gate that read the removed `preprocess_enabled` knob and short-circuited before resolution.
- Resolve rules as before, then branch: in strict mode (the `preprocess check` verb) return the resolved config directly so config validation is never gated by mode or trust.
- Add `_enforce_preprocess_mode` applied after resolution on the non-strict path: an empty config passes through unchanged; `off` returns empty with a debug log; `trust_all` returns the rules with a loud warning that trust checking is bypassed; `default` computes the resolved-set hash, and returns the rules only on a trust-record match, else empty plus one loud actionable warning naming the `preprocess trust` verb and the rule count.
- Import the config accessor and trust module function-locally in the enforcement helper to keep the module cheap to import from the spawn worker.
- Update the loader docstring to document the tri-state/TOFU gate and the strict bypass.

## Outcome

The loader is now the single enforcement point for the tri-state and TOFU gate (ADR D6). The loader and the spawn worker never prompt; trust is granted only via the CLI. Re-hashing the resolved set at every load means a changed rule set reverts a root to untrusted automatically. `preprocess check` (strict) still validates a malformed config regardless of trust. Every branch logs; there are no silent swallows. Ruff, basedpyright clean.

## Notes

`off` still parses the config before returning empty on the non-strict path; this is intentional so a malformed file is still surfaced via the parse warning, and it keeps the resolve-then-enforce flow linear for the strict-validation path.
