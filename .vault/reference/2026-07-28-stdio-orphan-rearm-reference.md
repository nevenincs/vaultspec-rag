---
tags:
  - '#reference'
  - '#stdio-orphan-rearm'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
body_hash: 'sha256:7ee3d402c979ca86a1a5c557d3ad2cd0d33d824da871b93e9f8c16d7715258db'
related: []
---

# `stdio-orphan-rearm` reference: `measured windows stdin-pipe and process-ancestry behaviour`

## Summary

Four platform behaviours were measured directly on the target platform
(Windows 11 Pro 26200, Python 3.13.11) while diagnosing shim processes that
outlived their clients by 20.6 hours. Each was run as an isolated probe;
two of the four contradicted the hypothesis that motivated them, and one
rules out the repair that reads as most obvious.

### Stdin resolves the pipe creator correctly

`GetNamedPipeServerProcessId` on an inherited stdin handle returns the
spawning process, not the shim itself. A child spawned with a piped stdin
resolved its parent's PID on both its stdin and stdout handles.

This refutes the hypothesis that the shim holds the pipe's *server* end and
therefore resolves itself. The precise anchor works; the fallback path is
where the orphans came from, and the fallback is what needed repair.

### The same query blocks forever behind a pending read

The decisive measurement. A child resolved its stdin creator successfully
on the main thread, then started a thread blocking in a read on that same
handle, then repeated the identical query: the second call never returned.
The probe emitted its pre-reader and reader-pending checkpoints and nothing
after, across repeated runs.

Stdin is a synchronous file object, so a pipe query serialises behind the
pending read and is never scheduled. The consequence is that re-resolving
the client after the transport has started - the first repair the defect
report proposes - hangs the watchdog thread permanently and silently. Any
re-arm path must read process ancestry, which locks nothing, and the
resolver must stay main-thread and install-time only.

### Peeking the pipe cannot detect the dead client either

Considered and discarded without a probe, on the transport's own recorded
behaviour: the client's inherited write handle survives the client, so the
pipe is not broken and a non-destructive peek would report it healthy. That
same fact is why stdin EOF never arrives, which is what makes the disarm
permanent rather than merely slow.

### A venv python.exe is a resident trampoline

Under a uv-managed virtual environment `sys.executable` differs from
`sys._base_executable`, and spawning the former inserts a generation: the
trampoline stays resident as the real interpreter's parent for that
interpreter's whole life, and killing the trampoline takes the child with
it.

Two consequences. In this spawn shape the direct-parent anchor is immortal
and no orphan can form beneath it, so the reported orphans came from `uv`
wrapper processes that do exit independently. And a test needing a genuine
orphan must run the orphaned process under the base interpreter, with the
venv site-packages and the source root supplied explicitly, or the
trampoline anchors it forever. An initial reading that the child survived
the kill was wrong: the output examined was buffered from before it.

### Enumeration and handle-opening disagree by design

Toolhelp snapshot enumeration lists processes without requiring rights on
them; `OpenProcess` requires rights and is refused for a higher-integrity
target. A live ancestor can therefore be visible to one walk and invisible
to the other, and only the enumeration walk distinguishes "cannot inspect"
from "not there". A reap decided on the handle walk alone would kill shims
whose clients are alive but privileged.
