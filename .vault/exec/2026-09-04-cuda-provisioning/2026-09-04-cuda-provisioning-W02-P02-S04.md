---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:85ddf89ea502d020b1f4a49411a314015fd0b59b9947a7703671a55a72a8dba7'
step_id: 'S04'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Prove the harness reproduces the held-environment destruction, the resolve-stage safe failure, and a real uv receipt the matcher accepts

## Scope

- `src/vaultspec_rag/tests/test_tool_env_provisioning_hostile.py`

## Changes

- `A src/vaultspec_rag/tests/test_tool_env_provisioning_hostile.py`

## Notes

The first run failed on the receipt-matcher proof, for a real reason: the
shipped matcher only recognises a requirement NAMED torch, so a stand-in called
`torchstub` could never satisfy it. The stand-in now carries the name `torch`
and is served from the loopback index under `--no-index`, so nothing resolves
to the real distribution.

Guard proof: dropping the URL comparison from the matcher failed
`test_the_matcher_rejects_a_receipt_pinning_a_different_wheel` on
`assert not ...` with `assert not True`. Restored. Zero MUTATION markers remain
and the mutated file is byte-identical to its committed state.

The remaining assertions in this file characterise uv rather than this
project's code - what a blocked removal does, where a direct URL is recorded,
what an unreachable wheel leaves behind - so no mutation of ours can falsify
them. They are honest characterisation tests, and their value is that they will
fail when uv's behaviour changes under us.

Incident, recorded because it breached a campaign constraint. A second mutation
removed `UV_TOOL_DIR` from the sandbox environment to prove the redirect is
load-bearing. It proved that, and in doing so installed the stand-in tool into
the operator's real uv tool directory. The tool was uninstalled immediately and
the real installation verified intact. The lesson is that the isolation
mechanism is the one thing a guard mutation must never target: breaking it does
not fail safely, it escapes the sandbox.
