---
tags:
  - '#research'
  - '#graceful-windows-service-stop'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:9d63e3c977f73a3695050b1fbcf4a46fafbe5aeae84a1e9bea380e21ff0ab269'
related: []
---

# `graceful-windows-service-stop` research: `console-independent graceful daemon stop on Windows`

`server stop` cannot gracefully shut down the search daemon on Windows: the
daemon is spawned detached from any shell (its own hidden console, or none), and
the operator stop runs as a separate, unrelated process, so a console-scoped
`CTRL_BREAK` cannot be delivered to the daemon - the stop always degrades to a
`TerminateProcess` force-kill. On Unix the equivalent `SIGTERM` is delivered
cross-process and drives the daemon's own lifespan teardown, so the graceful
path exists there but is absent on Windows. The force-kill is tolerated today -
the vector store recovers from an abrupt stop, and the stop process reaps the
daemon's owned Qdrant child and clears its discovery pointer - so this is a
robustness improvement, not a correctness gap, and it is post-0.3.4 follow-up.
The question this research frames for the ADR: which console-independent trigger
the daemon should expose so an operator stop drives its own graceful shutdown on
Windows.

## Findings

### The barrier is console isolation, not signal targeting

No choice of target pid makes `CTRL_BREAK` work from `server stop` on Windows.
`GenerateConsoleCtrlEvent` (what `os.kill(pid, CTRL_BREAK_EVENT)` invokes) signals
only a process group that shares the caller's console; the daemon is spawned in
`src/vaultspec_rag/cli/_process.py` with `CREATE_NO_WINDOW` (breakaway path) or
`DETACHED_PROCESS` (fallback), so it shares no console with a later, unrelated
stop process, and there is no `AttachConsole` step. Addressing the process-group
leader instead of the serving descendant changes nothing - both are equally
unreachable. This is distinct from the in-harness test cleanup, where the daemon
stays attached to the harness's console and a group-leader break does reach it.

### Option space for a console-independent trigger

- An in-daemon HTTP shutdown route the running service serves (the stop CLI
  already talks to the daemon's `/health` port), flipping the server's
  `should_exit` so the ASGI server runs its normal graceful shutdown.
  Cross-process, console-independent, works for both spawn modes. Favoured on
  first read; the ADR must settle authorization (the route must not let an
  unprivileged local caller stop the machine singleton) and how it composes with
  the existing force-kill fallback.
- A shutdown-sentinel file the daemon watches and self-stops on. Simpler
  transport, but adds a poll loop and a new filesystem contract that races the
  existing status-file lifecycle.
- An `AttachConsole(daemon_pid)` + `GenerateConsoleCtrlEvent` + restore dance in
  the stop CLI. Reuses the existing signal path but works only for the
  `CREATE_NO_WINDOW` spawn (a console exists to attach to), not the
  `DETACHED_PROCESS` fallback (no console), and risks disturbing the stop CLI's
  own console. Weakest.

Not investigated: whether a graceful Windows stop is worth the surface at all,
given the force-kill is already tolerated by storage crash-recovery and the stop
process's own reap of the owned Qdrant child and pointer clear - a scope question
for the ADR.

## Sources

- `src/vaultspec_rag/cli/_process.py` - the Windows daemon spawn (detached, new
  process group).
- `src/vaultspec_rag/cli/_service_stop.py` - the operator stop path that
  force-kills on Windows.
- RFC 9110 - HTTP semantics, for the shutdown-route option.
