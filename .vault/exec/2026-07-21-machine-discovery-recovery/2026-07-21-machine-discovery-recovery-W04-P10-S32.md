---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:72fe2218bb40b8ac8f5a3dd4641b5962360f51484eb272da2ae1097838ef68cd'
step_id: 'S32'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Correct the server stop path documentation to state that on Windows the stop degrades to a TerminateProcess force-kill because the daemon is spawned detached and cannot receive a cross-console CTRL_BREAK from a separate stop process, which is bounded and safe but not a graceful in-daemon shutdown

## Scope

- `src/vaultspec_rag/cli/_service_stop.py`

## Description

- State in the `server stop` command docstring that graceful shutdown reaches
  the daemon only on Unix, through a cross-process `SIGTERM` that drives the
  daemon's own lifespan teardown, and that on Windows the stop degrades to a
  `TerminateProcess` force-kill (`src/vaultspec_rag/cli/_service_stop.py`).
- Correct the terminate-path comment that framed the Windows force-kill as a
  mere expired drain window, naming the real cause: the detached daemon shares
  no console with a separate stop process, so a console-scoped `CTRL_BREAK`
  cannot be delivered to it and the escalation force-kill is what stops it.

## Outcome

The operator stop path no longer promises a graceful Windows shutdown it cannot
deliver. On Unix, `server stop` still drives the daemon's own teardown through a
cross-process `SIGTERM`, escalating to `SIGKILL` only if the drain window
expires. On Windows, the daemon is spawned detached from any shell, so a later,
unrelated stop process shares no console with it; a console control event can
only reach a process group that shares the caller's console, and there is no
console-attach step, so the graceful signal always fails and the escalation
`TerminateProcess` is what actually stops the daemon. That force-kill is abrupt -
the daemon runs none of its own teardown, because an external `TerminateProcess`
runs no in-process code - but it is tolerated: the vector store recovers from an
abrupt stop, and the stop process itself reaps the daemon's owned Qdrant child
and clears its discovery pointer. It is not a graceful in-daemon shutdown, and
the audit trail is the CLI-side mirror line rather than the daemon's own shutdown
record. Documentation only; no behaviour changed.

## Notes

Corrected scope. This Step was first scoped as a code fix that would route the
operator-stop graceful signal to the process-group leader, mirroring the sibling
test-cleanup fix. Tracing the production spawn showed that fix would be a no-op:
the barrier is not which pid is addressed but that a detached daemon cannot
receive a console control event from an unrelated process at all, so
re-addressing the same undeliverable signal to a different pid changes nothing.
A genuinely graceful Windows operator-stop needs a console-independent trigger -
an in-daemon HTTP shutdown route, or a shutdown sentinel the daemon watches -
which is a separate feature filed as follow-up work, not a documentation fix.
The honest documentation is the correct closure here; the forced kill is already
tolerated by storage crash-recovery and by the stop process's own reap of the
owned Qdrant child and clearing of the discovery pointer.

No code behaviour, test, or vault reference appears in the source; the change is
confined to a command docstring and an inline comment.
