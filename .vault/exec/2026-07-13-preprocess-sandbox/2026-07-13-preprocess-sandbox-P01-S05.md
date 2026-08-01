---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:3f6f1b62e1319699c5f93c5a6daa4e10d499e2184335667a8a39236cc05d22ae'
step_id: 'S05'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Rework the preprocess-config unit tests off the trust store onto the resolve-for-any-root and kill-switch behavior

## Scope

- `src/vaultspec_rag/tests/test_preprocess_config.py`

## Description

- Rework the preprocess-config unit tests off the trust store: delete the trust/hash/durability tests and the `_preprocess_trust` import, drop the trust-all fixture default (the fixture now clears both mode env vars so the resolved mode is the on-sandbox `default`), and add assertions that rules resolve for any root with no trust record, that `off` yields empty with a debug log, that `unsandboxed` resolves rules, that `off` wins over `unsandboxed`, and that strict bypasses the kill switch.
- Rework the CLI tests: remove the trust/untrust command tests and their help parametrisation, retarget the status assertions at the new envelope (mode, config presence, rule count, sandbox backend, would_run), make `run-one` execute without a trust act under the default mode, and repoint the flag-forwarding tests (`_service_child_env`, `_apply_preprocess_env`, the conflict cases) at `--preprocess-unsandboxed` / `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED`.
- Add regression guards asserting both the retired `PREPROCESS_TRUST_ALL` enum member and the trust/untrust verbs are gone.

## Outcome

Both files exercise the resolve-for-any-root and kill-switch behavior with real fixtures and no mocks or skips. Ruff and basedpyright are clean, and the two files pass: 54 tests green.

## Notes

Isolated `VAULTSPEC_RAG_STATUS_DIR` to a tmp path for the run. No skips, mocks, or tautological assertions were introduced.
