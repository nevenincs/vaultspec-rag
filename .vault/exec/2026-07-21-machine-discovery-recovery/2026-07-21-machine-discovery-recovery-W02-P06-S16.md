---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:24749d1ac61d89215f9d3ae63a99e65172324207722c458e81eec0cd16ff8d73'
step_id: 'S16'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Verify human and JSON status and doctor outcomes preserve typed discovery evidence

## Scope

- `src/vaultspec_rag/tests/test_cli_status.py`

## Description

- Cover the unchanged stopped contract when nothing holds the singleton.
- Cover a real held lock with no published pointer reporting degraded in JSON, carrying
  the reason, the holder identity, and the rendered evidence.
- Cover the human summary naming the condition instead of reporting stopped.
- Cover doctor and status agreeing about the same live holder.

## Outcome

The typed evidence is proven to survive all the way to both operator surfaces in both
output modes, and the stopped contract is proven unchanged for a genuinely unheld
singleton.

## Notes

One run of the doctor assertion failed and then passed four consecutive reruns of the same
selection. It was not dismissed as a flake: the likely cause is that the doctor also probes
installed dependencies, which can fail for reasons unrelated to discovery while another GPU
suite saturates the device, and the test would then have reported that as an opaque parse
error. The test now asserts the invocation produced output, and surfaces the underlying
exception when it did not, so a recurrence names its own cause instead of misattributing
the failure to discovery.
