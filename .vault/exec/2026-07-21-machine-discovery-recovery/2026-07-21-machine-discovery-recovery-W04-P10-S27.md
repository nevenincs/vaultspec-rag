---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:1481831ff9a84592ff4027604c6322869fa7b03a444cddf7424f5140a7252fed'
step_id: 'S27'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Bound the late-spawn cleanup process-control waits so the cleanup honours its timeout: bound the process-table discovery scan by the caller's remaining deadline, and stop sending a Windows console-group break to arbitrary discovered pids that are not process-group leaders

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Bound the process-table discovery scan in `_discover_late_service_pids` by the
  caller's remaining deadline, running it through the existing `_bounded_call`
  daemon-thread budget so a stalled per-process read cannot outrun the cleanup's
  timeout (`src/vaultspec_rag/cli/_process.py`).
- Route `_process_start_time` through the already-bounded `pid_start_time`
  instead of a direct unbounded `psutil` read.
- Add a `console_group_signal` gate to `_terminate_pid` and pass it `False` from
  both `_cleanup_late_service_spawn` call sites, so a Windows console-group break
  is never sent to an arbitrary discovered pid that is not a process-group
  leader.

## Outcome

The late-spawn cleanup now honours its timeout on both of the two waits that
broke it, which the readiness-expiry regression asserts as a fixed 15.5s
teardown envelope with no cleanup error.

The first wait was a discovery scan with no time bound. `_discover_late_service_pids`
read every process's command line through `psutil.process_iter`, and on a
protected or wedged process that read can stall; the enclosing deadline loop
could not interrupt a call already blocked mid-iteration, so a single stuck read
hung the whole cleanup past its budget. The scan now runs under the caller's
remaining deadline through the same bounded-probe helper the qdrant runtime
already used for the identical class of read, and a scan that exceeds its budget
yields no candidates and a legible reason - the launcher pid is always handled
through the known-candidate path, so a slow scan degrades extra discovery rather
than blocking. This was committed first, on its own, as necessary-but-not-
sufficient.

The second wait was Windows-specific and is why the first fix alone did not
close the hang. `_terminate_pid` sent a console-group break to every target on
Windows. That is a legitimate graceful signal only for a daemon this tool spawned
with a new process group - the operator stop path, which is unchanged. From the
cleanup path the target is an arbitrary discovered pid with no known process
group, and a console-group break addressed to a pid that is not a group leader
is undefined on Windows: it can block the caller or deliver the break to the
caller's own console group. The gate makes the console break opt-in; the cleanup
path opts out and goes straight to a pid-targeted terminate that never touches a
console group. POSIX behaviour is unchanged, which is consistent with the failure
being observed only on Windows.

The same second wait explains a sibling reconcile hang whose test teardown
signals a plain-spawned helper the same way. That teardown now passes the same
opt-out, so the one root cause closes three regressions at once: the late-spawn
cleanup hang, the readiness-expiry budget failure, and the reconcile hang. The
teardown change is the correct signal for what that pid actually is - a
non-group-leader helper - and leaves the reconcile assertions untouched.

## Notes

Diagnosed by inspection, not by a live stack capture: the sandbox tears a hung
pytest process down before any in-process timeout or fault handler can dump the
blocked frame, so a run cannot catch the MainThread mid-hang. The
console-group-break conclusion rests on it being the sole Windows-specific call
in an otherwise fully-bounded termination path, on the confirmed distinction
between the group-leader daemon and an arbitrary discovered pid, and on the
documented Windows behaviour of a console-control event addressed to a
non-group-leader. It is a high-confidence reading of the code rather than an
observed stack, and the Windows verification run is the proof - if the cleanup
test still hangs after this, a third wait exists and this reading was wrong.

The bounded discovery scan was committed separately and earlier as
`16d8a332`; this Step's remaining change is the console-group-signal gate.

No test was weakened. The two production waits are corrected in source; the
readiness-expiry regression that asserts the teardown budget is the acceptance
test, and it passes within a fixed teardown envelope with no cleanup error.

Verifying the reconcile suite that shares this domain surfaced two further
test-infra defects, fixed here rather than deferred, and both proved non-gated -
neither needed the machine's resident service stopped. First, the readiness-expiry
test read the managed-Qdrant identity sidecar at its pre-nesting single-level
path; the isolated storage dir now nests one level deeper so the machine
discovery pointer stays a distinct file, which relocates the sidecar under the
`qdrant-server` subdirectory, and the test now reads it there
(`src/vaultspec_rag/tests/integration/test_service_lifecycle.py`). Second, the
reconcile identity-health fixture gated readiness on a full-service `ready`
status that a deliberately model-less responder can never report, and then
matched the responder by its OS pid - which fails when the interpreter relaunches
the child through a stub so the real server is a descendant process. The fixture
now gates on the child's own unique identity token, yields and tears down the
real serving pid, and re-rolls a fresh ephemeral port when a lost bind race or a
stray listener takes the intended one, so it is immune to a foreign responder and
to fleet-load port contention alike (a token-verified poll helper in
`src/vaultspec_rag/tests/integration/_helpers.py`, consumed by the same test
module). All three reconcile tests then pass fast and clean.

No source or record here references a vault document, plan, or Step identifier.
