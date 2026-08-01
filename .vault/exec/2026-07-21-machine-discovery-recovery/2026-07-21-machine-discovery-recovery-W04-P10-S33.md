---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:3964a5f9e97a810a4718079fed623cef1239fffce353081c62f92c63f4474cdf'
step_id: 'S33'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Route the real-daemon test cleanup graceful signal to the spawned group-leader process rather than the discovered descendant daemon pid so a relaunched daemon receives the console break and shuts down gracefully, escalating to a pid-targeted force-kill on both when the graceful drain does not complete

## Scope

- `src/vaultspec_rag/tests/integration/conftest.py`

## Description

- Route the real-daemon test cleanup's graceful signal to the spawned process
  (the process-group leader created with a new process group) rather than the
  status-discovered descendant daemon pid, so the console break propagates
  through the group and reaches the daemon
  (`src/vaultspec_rag/tests/integration/conftest.py`).
- Wait the full remaining budget for the descendant daemon to complete its own
  graceful shutdown, then escalate to a pid-targeted force-kill on both the
  descendant and the leader with the console-group signal disabled.

## Outcome

Both real-daemon restart and shutdown regressions now stop the daemon gracefully
in every daemon life instead of hanging on the second life. The cleanup helper
resolves the serving daemon pid from the status file, but on this host the
interpreter relaunches the spawned process through a stub, so the serving daemon
is a descendant of the process the harness launched with a new process group and
is not itself a group leader. A Windows console break addressed to that
descendant is undeliverable; the previous cleanup sent it there, so the daemon
never received a shutdown signal and the second daemon life stranded with no
shutdown lines. The fix sends the bare graceful signal to the group leader - the
same signal the working first daemon life sends explicitly - which propagates
through the process group to the descendant daemon, then waits the full budget
for the daemon's own graceful teardown before escalating to a pid-targeted
force-kill on both the descendant and the leader. The restart regression and the
interrupt-then-reopen shutdown regression both pass, each exercising two full
daemon lifecycles.

## Notes

The console-sharing distinction between the test daemon and the production
daemon is the crux and worth recording. The test daemon is spawned into a new
process group but stays attached to the harness's console, so a console break
from the harness reaches its group. The production daemon is spawned detached
from any shell, so the same class of signal is undeliverable to it from a
separate stop process - which is why the sibling production stop path is
documented as a force-kill rather than fixed by the same reroute. The bare
group-leader signal is used deliberately rather than the shared terminate
helper, whose short internal graceful drain would force-kill the leader before
the daemon's worker-release and store-close sequence completes.

Verified by two real-daemon runs on this host: the restart regression and the
interrupt-then-reopen shutdown regression each pass with both daemon lifecycles
clean.

No source, test, or record here names a vault document, plan, or Step
identifier.
