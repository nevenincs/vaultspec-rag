---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S24'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Repoint the five interception points that patch the command-line probe symbol to the new target, and prove at least one still catches its intended failure by mutating the token comparison to confirm it goes red and restoring it

## Scope

- `src/vaultspec_rag/tests/test_cli_status.py`

## Description

- Repoint the five interception points from the deleted command-line symbol to
  the transport function as bound in the process module, in
  `src/vaultspec_rag/tests/test_cli_status.py`.
- Repoint two direct-call tests in the service-status module to the owner.

## Outcome

The five interception points patched a package attribute, which worked only
because the identity helper resolved the probe as a package attribute at call
time. Repointing that helper to a bound import would have made those patches
inert: the tests would have called the real probe, received the unreachable
sentinel, fallen through to the executable-name check, and in at least some cases
still passed - while no longer testing the token comparison they exist for.

That failure mode is why this Step exists separately from the repointing Step
rather than folded into it. A test that cannot fail is worse than a missing test,
because it reports a safety it is not providing.

The interceptions now patch the transport function as bound in the process
module, which is where the identity helper resolves it. Two further tests called
the deleted symbol directly and now call the owner.

## Notes

The proof required by this Step was performed by the harness operator rather than
by the author, who operates under a standing instruction not to execute tests. It
was run as one uninterrupted sequence, and both directions are recorded here
because a green result alone would not distinguish a live interception from an
inert one.

Under mutation - the token comparison replaced so a mismatched token would be
accepted - the mismatch test FAILED, on the assertion that the identity helper
returned true for a token that does not match. That is the required result: it
proves the interception reaches the comparison rather than falling through to the
executable-name path, which is the specific way this test could have become
vacuous when the probe symbol moved.

After restoring the comparison the same test PASSED. The operator additionally
confirmed the restoration by diff rather than by eye, reporting that the
mutate-and-restore round trip left no net change beyond this Step's intended
edits, so no fragment of the weakened comparison survived.

The proof is complete and this Step's central risk is closed: the five repointed
interceptions still test what they claim. A future reader may rely on that, and
should be correspondingly sceptical of any similar repointing elsewhere in this
codebase that lacks an equivalent recorded result.
