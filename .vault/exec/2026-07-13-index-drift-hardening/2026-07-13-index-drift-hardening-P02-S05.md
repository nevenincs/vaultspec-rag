---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:14573104b2dcfebeee979c80855f8fc73fa26aeb851ed4e7e860eb81cd144960'
step_id: 'S05'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Remove PREPROCESS_ENABLED outright (enum, override map, config field, default) and add the tri-state preprocess_mode resolved from VAULTSPEC_RAG_PREPROCESS and VAULTSPEC_RAG_PREPROCESS_TRUST_ALL with default meaning on-with-TOFU

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Remove the `PREPROCESS_ENABLED` enum member and add two env members, `PREPROCESS` (kill switch, `=off`) and `PREPROCESS_TRUST_ALL` (force trust-all).
- Drop the `preprocess_enabled` entry from the single-var env override map; the tri-state resolves from two vars in a dedicated property, so it is deliberately absent from that map.
- Replace the `preprocess_enabled: False` default with `preprocess_mode: "default"` in the RAG defaults table.
- Add a module-level `PreprocessMode` literal and a valid-modes frozenset.
- Add a `preprocess_mode` property on the config wrapper that reads the two env vars live with the kill switch winning, then the base-config/CLI override, then the module default; an unrecognised configured value degrades to `default` with a warning rather than raising.

## Outcome

`preprocess_mode` resolves the tri-state (`default` | `trust_all` | `off`) with the required env precedence: `VAULTSPEC_RAG_PREPROCESS=off` forces off (wins over everything), `VAULTSPEC_RAG_PREPROCESS_TRUST_ALL=1` forces trust-all, unset means default. No back-compat alias for the removed knob (owner decision): a set legacy var is simply unread. Reading the env live in the property means a flag forwarded into the daemon env takes effect without a config rebuild, matching the `local_only` control-parity precedent. Ruff, basedpyright clean on `config.py`.

## Notes

The two-var resolution does not fit the single-var override map, so it lives in a property alongside the derived `code_noise_*` properties rather than in the map. Downstream test modules that still reference the removed `PREPROCESS_ENABLED` member (`test_cli_preprocess.py`, `test_config.py`, and the preprocess integration tests) are P03/P04 scope and are expected to fail until reworked.
