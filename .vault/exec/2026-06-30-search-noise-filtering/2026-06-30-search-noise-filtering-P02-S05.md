---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S05'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# Add noise-profile config keys (hide and demote domain sets, dedup default) with shipped defaults and unit tests

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add noise-profile keys to `_RAG_DEFAULTS`: `code_noise_hide_domains`
  ("worktree,generated"), `code_noise_demote_domains`
  ("tests,docs,locale,vendored"), `code_noise_demote_penalty` (0.3), and
  `dedup_locales_default` (True).
- Add `code_noise_hide_domains` / `code_noise_demote_domains` parsing properties
  validating tokens against `NOISE_DOMAINS` (unknown labels and `prod` dropped);
  hide wins over demote so the two sets never double-act.
- Wire env overrides for all four knobs (`EnvVar` members + `_ENV_OVERRIDE_MAP`).
- Tests: defaults, parse-set validation, hide-wins, env-override of penalty and
  dedup default.

## Outcome

`pytest test_config.py` -> 44 passed. The profile is overridable per host via
env and per project via base config, and feeds the searcher's policy pass.

## Notes

Domain sets are stored as comma strings (env-overridable, unlike the structured
intent profiles); the properties parse and validate them. Per-call CLI flags
(S06) override the profile at request scope.
