---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:49f18570c20ea61ad0b8692f0f9feb71a92145ae622d238c8de1410f70ba5d3b'
step_id: 'S05'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Replace the in-environment reinstall with a holder preflight that refuses and hands over the exact command

## Scope

- `src/vaultspec_rag/commands/_tool_torch.py`

## Changes

- `M src/vaultspec_rag/commands/_tool_torch.py`
- `M src/vaultspec_rag/tests/test_tool_torch_repair.py`

## Notes

The destructive invocation is gone rather than guarded. `_run_tool_reinstall`,
`_verify_tool_repair` and `_uv_failure_detail` are deleted along with the
`subprocess` import, so no path in the module can spawn a replacement, and a
test asserts that structurally rather than behaviourally - a refusal that only
avoids the call today is one refactor away from making it again.

`_service_holder_outcome` is folded into the holder preflight rather than kept.
It answered whether a machine service was running, which is neither necessary
nor sufficient: a daemon in an unrelated environment does not hold this one,
and a plain CLI invocation or an MCP server that has not yet claimed the
singleton does. The preflight asks the environment instead, so the exception
guard the old resolver needed no longer has a caller.

Terminal outcomes lost `UV_UNAVAILABLE`, `UV_FAILED`, `RECEIPT_UNVERIFIED`,
`REPAIRED` and `SERVICE_HELD`, none of which are reachable without a
replacement to run, and gained `HOLDER_DETECTED` and `HANDOFF_REQUIRED`. There
is deliberately no success value: this process runs inside the only environment
it targets, so every path ends in a refusal carrying the command.

Two tests were repointed in the same change rather than left exercising deleted
functions - the service-holder test now asserts the handoff, and the
verification test is replaced by one asserting the handoff reports a receipt
that already carries the pin.

Guard proof: replacing the refusal with a success outcome failed
`test_a_defective_tool_is_handed_off_rather_than_replaced` on its action
assertion. Restored; zero MUTATION markers remain. Gates: ruff, ty, and 24
provisioning plus 176 install tests green.
