---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S13'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Prove the drift self-heal and TOFU enforcement end-to-end against real backends: an ignore-file edit prunes stale chunks on the next watcher or reindex run, an untrusted preprocess config skips with the loud warning while a trusted one executes, and the trust store isolates via the status-dir knob

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

- Replace the removed enable-knob fixture with `_preprocess_env`: isolate the
  managed status dir (the trust store's home) to a per-test tmp path and
  default the module to trust-all so the extractor-behavior tests keep
  exercising the real subprocess path.
- Add a `_default_mode` fixture that drops the trust-all opt-in so individual
  tests run under the on-with-TOFU default.
- Add a `_sentinel_extractor` helper: a real extractor script that proves
  execution by creating a sentinel file while emitting valid output.
- Replace the old disabled-gate RCE proof with the kill-switch tier: `off`
  outranks the module's trust-all and executes nothing.
- Add the TOFU tier RCE proof: an untrusted root under the default mode
  executes nothing and the skip warning names the `preprocess trust` verb.
- Add the TOFU round trip: a recorded trust hash lets the command run; editing
  the command reverts the root to untrusted and nothing executes.
- Add the consumer-reported drift scenario end to end: index two files, newly
  ignore one, forward only the ignore file down the scoped path (the exact
  watcher invocation) and assert the membership-epoch escalation prunes the
  stale chunks while retaining the unrelated file.

## Outcome

All ten tests in the module pass against the real GPU and Qdrant backends
(57s); ruff and basedpyright report zero findings on the module. The three
security proofs are sentinel-based (execution leaves a file), so a regression
cannot mask itself as a skip.

## Notes

The trusted-root round trip records trust via the store helpers directly
rather than the CLI verb; the CLI trust flow is covered separately by the P03
unit tests. No skips, mocks, or scaffolds.
