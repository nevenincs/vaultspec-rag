---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` `W04.P10` summary

## Description

This Phase carried the discovery work from focused regression coverage to a proven
end-to-end lifecycle, and absorbed nine shutdown and process-control corrections
found while proving it. It is the Phase that closes the plan: with its final Step
verified, the plan stands at 33 of 33 Steps.

The regression sweep and the end-to-end run bracket the Phase. Between them sit the
corrections that the attempt to run real daemons exposed, each one a place where a
bounded operation was in fact unbounded: a process-table scan that ignored the
caller's deadline, a store teardown that could wait forever on a wedged consumer's
writer lock, an interpreter exit that a stalled periodic worker could hang, and
discovery-publisher guard acquisitions that could strand teardown before any
shutdown line was logged. Each gained a finite deadline. A Windows console-group
break that was being sent to arbitrary discovered pids was narrowed to genuine
process-group leaders. The authoritative running-phase publication was made
fail-loud, so a daemon that cannot record its running-owner claim rolls back rather
than serving under an unproven claim. The documented stop path was corrected to
state plainly that on Windows the stop degrades to a force-kill, because a detached
daemon cannot receive a cross-console break from a separate stop process - bounded
and safe, but not a graceful in-daemon shutdown, and previously described as if it
were. Test cleanup was repointed at the spawned group leader so a relaunched daemon
actually receives the console break, escalating to a pid-targeted force-kill only
when the graceful drain does not complete.

The closing verification ran the whole real-process lifecycle suite against
committed `61ce0d79` in a clean extract: 32 passed, 0 failed, in 12 minutes 32
seconds. It exercised start, identity corruption, heartbeat repair, reconcile,
search resolution, and clean shutdown, each through a named test rather than by
inference. Running from a clean extract rather than the shared development tree was
decisive rather than cautious - the shared tree carries an unrelated red test in the
install and torch-configuration surface from a concurrent refactor, and the same
test passes in the extract.

The mandatory architecture and safety review returned PASS, finding ownership,
degraded-versus-absent resolution, and the read-only reconcile sound on every
reviewed axis, and confirming the contract document matches the code. It deferred
execution evidence to the final Step because the discovery tests can touch the live
machine singleton and the device was in use; that evidence now exists.

- Modified: `src/vaultspec_rag/cli/_process.py`
- Modified: `src/vaultspec_rag/cli/_service_stop.py`
- Modified: `src/vaultspec_rag/store.py`
- Modified: `src/vaultspec_rag/_store_locks.py`
- Modified: `src/vaultspec_rag/service.py`
- Modified: `src/vaultspec_rag/server/_lifecycle.py`
- Modified: `src/vaultspec_rag/server/_lifespan.py`
- Modified: `src/vaultspec_rag/server/_main.py`
- Modified: `src/vaultspec_rag/server/_state.py`
- Modified: `src/vaultspec_rag/server/__init__.py`
- Modified: `src/vaultspec_rag/tests/test_machine_discovery.py`
- Modified: `src/vaultspec_rag/tests/integration/conftest.py`

## Verification

The focused discovery, status, doctor, transport, lifecycle, and singleton
regression suites pass. The unfiltered real-process lifecycle suite passes at 32 of
32 against committed `61ce0d79`, with no marker narrowing and no first-failure stop.
The mandatory review returned PASS.

Two low follow-ups stay open on the review's own recommendation, neither gating
closure: anchor the contract document's code citations to symbol names so they do
not rot against a moving file, and reject an owner-less discovery pointer on the
read side to mirror the invariant the publisher already enforces on write. A third
finding is informational and deliberately carried forward - this Phase's
pointer-sourced reconcile identity check is the working template for the deferred
tautological-identity fix in the service health client, where the expected token was
taken from the same response it was then compared against.

Two Steps closed earlier in this Phase carry no execution record. That gap predates
this Step and is recorded here rather than repaired, because writing a record for
work another agent performed would assert evidence this Phase did not gather.
