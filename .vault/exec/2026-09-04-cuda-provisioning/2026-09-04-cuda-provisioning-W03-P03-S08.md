---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:b4dd03e2ea5510a03d6bd227023f205802d1a323faa957e6ba4c03eb15401405'
step_id: 'S08'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Prove repair safety and receipt postconditions, including that a refusal launches no uv child

## Scope

- `src/vaultspec_rag/tests/test_tool_torch_repair.py`

## Changes

- `M src/vaultspec_rag/tests/test_tool_torch_repair.py`

## Notes

The Step is the one absorbed from the tool-mode-cuda plan, whose original
scope included verifying a repair's receipt postconditions. That verification
no longer exists - S05 deleted it with the replacement it followed - so what
is proven here is the shape the transaction actually has: every terminal
outcome, and that a real holder reaches the operator by pid.

`CUDA_UNVERIFIED` has one producer rather than the two the plan anticipated,
for the same reason: the post-install verifier that produced the second is
gone. The pre-flight producer is covered by the existing device-visibility
test.

Ten tests added: ALREADY_READY, NOT_APPLICABLE, DRY_RUN, a table over every
blocking action, a table over every non-blocking one, and a real-holder
refusal built on the harness - a real tool environment installed in a
redirected sandbox, held by a real process, asserting the pid and the phrase
an operator acts on both appear in the detail.

Guard proof. Removing HOLDER_DETECTED from the blocking set failed the
blocking table on `assert outcome.blocks_install`. A first attempt at the
holder mutation removed only the section heading and failed nothing - the
mutation was weak, not the test, since the assertion is about the per-holder
lines that follow it. Dropping those lines instead failed the real-holder test
on `assert f"pid {holder.pid}" in outcome.detail`. Both restored; zero
MUTATION markers remain and the file is byte-identical to its committed state.
Gates: ruff, ty, 38 tests across the three provisioning files green.
