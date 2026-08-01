---
tags:
  - '#reference'
  - '#service-orphan-reaping'
date: '2026-07-24'
modified: '2026-07-25'
body_hash: 'sha256:d9e2c4592865261b6c247bfa74b48ffaddbcef568f0e5c49cd2287c4b1795d9f'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
  - "[[2026-07-23-service-orphan-reaping-adr]]"
---

# `service-orphan-reaping` reference: `launcher-daemon pair origin`

## Summary

The reap predicate in `src/vaultspec_rag/cli/_service_stop.py` assumes one
logical daemon enumerates as a launcher plus worker PAIR carrying the same
launch witness in a parent-child relation, and it protects or clears a whole
pair rather than half of one. That assumption was asserted from the shape of the
code, not measured. This reproduces a race-losing daemon in an isolated sandbox
and captures the real process tree, so the predicate rests on an observation.

The pair is confirmed on this host, and the mechanism is now named: the venv
`python.exe` is a trampoline that re-execs the real interpreter while preserving
the command line verbatim, so both processes carry the witness. A second,
unlooked-for finding is recorded alongside it: one production enumeration costs
tens of seconds on a host with a thousand processes, which bounds what the reap
can honestly observe.

## Sandbox

A probe process created a temp sandbox and pointed the status dir, the Qdrant
storage dir, and the Qdrant port at it before importing anything that resolves
config. Isolating the storage dir is what relocates the machine lock
(`<storage>/../service.lock`) and the machine discovery pointer
(`<storage>/../service.json`); isolating only the status dir would have left the
probe contending for the real machine singleton. The probe then acquired the
isolated machine-lock lease itself, which guarantees the spawned daemon loses
the singleton race rather than racing for it.

The daemon was spawned the way the CLI spawns it: the interpreter that
`_resolve_daemon_interpreter` returns, `-m vaultspec_rag.server --port <port>`,
detached, with an ephemeral service port. Host: Windows, Python 3.13.11, psutil
7.2.2, roughly 1030 live processes.

## The captured tree

Three processes descend from one spawn. Two are the daemon; the third is not.

| pid   | ppid  | image                                      | command line                                         |
| ----- | ----- | ------------------------------------------ | ---------------------------------------------------- |
| 66460 | 6032  | `.venv/Scripts/python.exe`                 | `...python.exe -m vaultspec_rag.server --port 59455` |
| 41620 | 66460 | `uv/python/cpython-3.13.11-.../python.exe` | `...python.exe -m vaultspec_rag.server --port 59455` |
| 64560 | 41620 | `System32/conhost.exe`                     | `conhost.exe 0x4`                                    |

The launcher (66460) is the pid `Popen` returns and the pid the CLI records. Its
image is the venv shim. The worker (41620) is its child and its image is the
real uv-managed interpreter - a different executable on disk, with a command
line byte-identical to the launcher's, because the shim re-execs rather than
rewriting argv. That identity is exactly why both processes match a witness
subsequence scan and why the pair, not the process, is the unit the reap must
reason about.

The two create times differ by 13 milliseconds, so there is no meaningful window
in which the launcher exists alone. The launcher waits for and propagates the
worker's exit: both left together and the launcher reported the worker's
non-zero code.

The `conhost.exe` child is a console host attached to the worker, not a daemon.
It carries no witness, so it never enumerates as a reap candidate, and it exits
with its owner. Recording it here is what makes "the tree has three processes,
the daemon has two" a measured statement rather than an assumption that the
child list contains only daemons.

## What the loser did before exiting

The loser published nothing: no machine discovery pointer, no status view, no
bound listener, no Qdrant child. It exited non-zero after roughly 40 seconds,
essentially all of which was cold interpreter and package import - the claim
itself refuses immediately once reached.

Its managed log carries, in order, the refusal traceback originating at
`_claim_machine_singleton`, the one-line cause naming the winning holder's pid,
and then the forced-exit witness line the backstop emits before calling
`os._exit`. That last line is the load-bearing one: a daemon that reached a
natural interpreter exit never writes it, so its presence is positive evidence
that the self-exit backstop fired rather than that the process happened to end.

## Enumeration cost, and what it bounds

`_orphan_daemon_pids` walks every process on the host reading command lines. On
this host that walk costs about 39 seconds on a cold call and 4 to 6 seconds on
a warm repeat within the same interpreter. `server stop --orphans` is a fresh
process every time, so it pays the cold cost. For comparison, enumerating pids
alone costs 2 milliseconds and enumerating pid plus ppid costs under a second;
essentially the entire cost is reading command lines.

Two consequences follow, and only the first is a limitation of the reap:

A sweep is not a snapshot. During one 39-second walk the probe's own daemon
lived and died, and the walk returned nothing at all - a process that exits
before the walk reaches it is dropped silently. The reap's target is an
ACCUMULATED orphan, which by construction persists across the window, so the
reap still finds what it exists to find. But no caller may use this enumeration
to observe a short-lived process, and a test that spawns a witness and expects
to enumerate it must keep that witness alive well past the sweep.

The safety anchors do not degrade with the sweep. The must-never-kill set is
computed from the machine-lock holder, the discovery pointer, and the pid
answering `/health` on the port - none of which come from the sweep. A truncated
or stale sweep can therefore only cause an orphan to be MISSED, never the
singleton to be killed. Under-reaping is recoverable by running the command
again; the inverse would not be.

## Scope of the observation

Measured on Windows only. The pair is a Windows venv-shim artefact: on POSIX the
spawn is a single process with no re-exec, which is why the test suite's
expected witness count per daemon is platform-conditional rather than fixed at
two. The pair-protection branches in the predicate are therefore exercised for
real only on this platform; on POSIX they are inert rather than wrong.
