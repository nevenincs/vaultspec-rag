---
tags:
  - '#research'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-27'
related: []
---

# `mcp-stdio-lifetime` research: `stdio shim orphan leak and lifetime hardening on Windows`

A user bug report (2026-07-16) documented that stdio MCP shim processes
(`vaultspec-search-mcp` and the companion `vaultspec_core.mcp_server.app`)
never exit when the client that spawned them dies or reconnects: over ~2 days
of Claude Code + Codex usage, 8 logical shims (~24+ OS processes) accumulated,
each a `uv.exe -> launcher .exe -> python.exe` chain, all pointing at the one
healthy machine-singleton backend. This research establishes why the shims
leak, which failure mode dominates, and what lifetime-hardening options exist,
grounding an ADR for `vaultspec-rag`'s half of the fix (the
`vaultspec_core.mcp_server.app` half belongs to the companion repo).

Environment stamped at research time: `mcp` SDK 1.28.0 in the project venv,
`uv 0.11.29`, Windows 11 Pro 10.0.26200, Python 3.13 venv.

## Findings

### L1 - The shim's only lifetime contract is stdin EOF; no backstop exists

The stdio branch of `main` in `src/vaultspec_rag/server/_main.py` delegates
entirely to `FastMCP.run(transport="stdio")`. The installed SDK's
`mcp/server/stdio.py` reads stdin via `anyio.wrap_file(...)`; its
`stdin_reader` task ends when the line iterator hits EOF, closing the read
stream and unwinding `run()`, after which the shim's `finally` block stops
watchers and closes the registry. There is no parent-liveness watchdog, no
idle timeout, and no other exit path anywhere in the codebase.

Source: `src/vaultspec_rag/server/_main.py:139-168`;
`.venv/Lib/site-packages/mcp/server/stdio.py` (mcp 1.28.0).

### L2 - Live audit: the dominant leak mode is a LIVE client abandoning old shim generations

A `Win32_Process` sweep on 2026-07-17 found many complete shim chains alive,
grouped by spawning ancestor. One live Codex process (PID 67892, started
07-15 16:29) owned four generations of shim pairs (07-15 16:30, 07-15 17:52,
07-16 23:32, 07-16 23:44) - three abandoned, one active. Several Claude Code
ancestors each held one live chain (plausibly active sessions). One chain's
ancestor was dead. So both reported modes are real, but the
client-alive/abandoned-generation mode dominates on this machine, and a
parent-death-only fix would not clear it.

Source: local `Get-CimInstance Win32_Process` audit, 2026-07-17 00:04 (+ user
report table of 2026-07-16 23:00).

### L3 - Repro EXP1: stdin EOF DOES terminate the full chain

Spawning `uv run --no-sync vaultspec-search-mcp` from a .NET
`System.Diagnostics.Process` with redirected stdin, then closing stdin,
terminated the entire 4-process chain (`uv.exe -> vaultspec-search-mcp.exe launcher -> venv python.exe -> base python.exe`) within 12 seconds. The SDK's
EOF contract and the uv/launcher chain propagation both work: when the python
worker exits, the launcher and uv.exe exit with it. The bug is therefore not
"the server ignores EOF" and not "uv fails to reap its child".

Source: scratchpad `eof_repro.ps1` experiment 1, 2026-07-17, this machine.

### L4 - Repro EXP2: no cross-generation handle-inheritance leak with a correct spawner

With two shim chains alive concurrently (same spawner), closing generation
A's stdin killed chain A within 12s while chain B kept running. A spawner
that scopes pipe-handle inheritance correctly (as .NET does) does not leak
the write end into sibling generations. The orphaning therefore requires
client-side behavior - either the client never closes the old generation's
stdin write handle on reconnect, or it "kills" the server by terminating the
direct child process only.

Source: scratchpad `eof_repro.ps1` experiment 2, 2026-07-17, this machine.

### L5 - Repro EXP3 (smoking gun): killing only the top uv.exe orphans the worker with its stdio intact

Force-killing only the chain's direct child (`uv.exe`) left the launcher and
both pythons alive indefinitely. Windows kills are single-process, not
tree-wide, and the python worker's inherited stdin pipe still connects it
directly to the (live) spawner, so no EOF ever arrives. This is exactly the
"client reconnect" shape: an agent harness that terminates its direct child
and respawns leaves a fully-functional orphan worker behind. A
parent-watchdog that watches only the *client* PID would also miss this when
the client stays alive; watching the *immediate ancestor chain* (uv.exe,
launcher) catches it, because the kill severs the chain above the worker.

Source: scratchpad `eof_repro.ps1` experiment 3, 2026-07-17, this machine.

### S1 - SDK trace: EOF handling is correct; the hang is a forever-blocked readline

Tracing installed `mcp` 1.28.0 + `anyio` 4.14.0: `stdin_reader` iterates
`async for line in stdin`; each `readline` is offloaded to a worker thread
via `to_thread.run_sync`. On EOF the loop breaks and `run()` unwinds cleanly
(consistent with repro L3). When EOF never arrives, the blocking `readline`
never returns, the task group never exits, and the process lives forever.

Source: `mcp/server/stdio.py:60-71`, `anyio/_core/_fileio.py:108-135`
(mcp 1.28.0, anyio 4.14.0 in the project venv).

### S2 - anyio worker threads are non-daemon and the read cannot be cancelled in-process

The anyio worker thread (`AnyIO worker thread`) is created non-daemon
(`anyio/_backends/_asyncio.py:977`), and `AsyncFile.readline` is offloaded
without `abandon_on_cancel=True`, so neither task-group cancellation nor a
timeout can abandon the in-flight read, and CPython shutdown would join the
wedged thread. Consequence: no in-process cancel/timeout can unwedge a
blocked stdin reader - a lifetime backstop must force process death
(`os._exit`), a pattern the codebase already uses to free the store lock in
the service-first search fallback.

Source: `anyio/_backends/_asyncio.py:977-1051,2534-2565`,
`anyio/_core/_fileio.py:125-126,270-272`; runtime check
`threading.current_thread().daemon == False` in this venv.

### S3 - uv's Windows kill-propagation fix is partial and does not cover this leak

uv historically did not kill grandchildren when killed
(astral-sh/uv#11817, #12692). PR #17500 (shipped uv 0.9.28, 2026-01-29) ties
the `uvx.exe`/`uvw.exe` wrapper to `uv.exe` via a Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, but that covers wrapper-to-uv only and
only fires when the client kills or closes the wrapper's job. Repro L5 (on
uv 0.11.29, well past the fix) shows killing the top uv.exe still orphans
the launcher and pythons. A uv version floor is defense-in-depth at best.

Source: github.com/astral-sh/uv issues #11817, #12692, PR #17500; repro L5.

### S4 - The mcp SDK's own Windows job-object kill is client-side only

`mcp/os/win32/utilities.py` (`create_windows_process`,
`terminate_windows_process_tree`) gives Python-SDK *clients* a
kill-on-job-close job object. Claude Code and Codex are not Python-SDK
clients, so none of that machinery protects the vaultspec shim. The shim
must defend itself.

Source: `mcp/os/win32/utilities.py:236-318` (mcp 1.28.0).

### S5 - Upstream pywin32 eager-import (#2233) is still unfixed; issue #184 stays blocked

`mcp/__init__.py:3` unconditionally does `from .client.stdio import ...`,
eagerly importing `win32api`/`win32job`/`pywintypes` on Windows (verified at
runtime in this venv on 1.28.0). python-sdk#2233 remains open; candidate PR
#2365 is unmerged. There is no version to floor to, so vaultspec-rag issue
#184 ("add mcp version floor once upstream fix ships") is not yet
actionable; the pywin32-postinstall remediation message in
`server/_main.py` stays.

Source: `mcp/__init__.py:3` (mcp 1.28.0);
github.com/modelcontextprotocol/python-sdk#2233, PR #2365.

### S6 - Ecosystem consensus: stdio servers own their lifetime server-side

The orphan class is widespread: upstash/context7#2542 (fixed by PR #2576 -
stdin close handler + parent-death polling + `process.exit(0)`),
microsoft/playwright-mcp#1568, larksuite/lark-openapi-mcp#59,
anthropics/claude-code#46637. The LSP 3.17 spec encodes the precedent:
`InitializeParams.processId` plus "if the parent process is not alive then
the server should exit its process". Consensus remediation is server-side
self-defense, not waiting for client fixes.

Source: the cited upstream issues/PRs; LSP 3.17 `InitializeParams`.

### S7 - Handle-inheritance mechanics: why the client's EOF never arrives

A pipe's read end sees EOF only when EVERY copy of the write handle is
closed. Any handle flagged `HANDLE_FLAG_INHERIT` is duplicated into every
child spawned with `bInheritHandles=TRUE` while it is open, and standard
streams propagate down each generation by design (`STARTF_USESTDHANDLES`).
A client that spawns successive shim generations with inheritable pipe
ends therefore leaks generation A's stdin writer into generation B, and
closing its own copy no longer produces EOF for A. The correct fixes
(`SetHandleInformation(..., HANDLE_FLAG_INHERIT, 0)` or the
`PROC_THREAD_ATTRIBUTE_HANDLE_LIST` allow-list) live in the spawner - out
of our reach. Rust `std::process` (uv's spawner) is defensive here, which
matches repro L4: the residual leaker is the client, and a watchdog
independent of stdin is warranted regardless.

Source: MS Learn "Inheritance" and "Creating a Child Process with
Redirected Input and Output"; teammate research F1-F4.

### S8 - Cross-platform fast paths and their races (future work)

Linux `prctl(PR_SET_PDEATHSIG, SIGTERM)` requires an immediate
`os.getppid()` re-check (a parent that died before the call never sends
the signal, and the signal keys on the parent thread); macOS has kqueue
`EVFILT_PROC`/`NOTE_EXIT`. The portable floor is polling `os.getppid()`
for reparenting - what the shipped POSIX fallback does; the poll-based
approach has no set-then-check race. A two-tier shutdown (graceful httpx
close, then a 2-3s deadline into `os._exit`) was considered and rejected
in the ADR: the shim holds no GPU or store resources worth a graceful
pass, and straight hard-exit removes the hang window entirely.

Source: man7 `PR_SET_PDEATHSIG`; `kqueue(2)`; teammate research F12-F16.

### W1 - Prototype: ancestor discovery and death-wait both work from unprivileged ctypes

A scratchpad prototype (no pywin32) walked the parent chain via
`CreateToolhelp32Snapshot`, correctly discovering the full real ancestor
chain (python -> pwsh -> pwsh -> claude -> pwsh -> tmux, 6 levels), with a
creation-time monotonicity check (`GetProcessTimes`: an ancestor must have
been created before its child) as the PID-reuse guard. In an isolated test,
`OpenProcess(SYNCHRONIZE)` on a victim process followed by taskkill and
`WaitForSingleObject(h, ...)` returned `WAIT_OBJECT_0` immediately. The
watchdog design is implementable with ctypes alone in the shim process.

Source: scratchpad `watchdog_proto.py` + isolated `WaitForSingleObject`
test, 2026-07-17, this machine.

### W2 - ctypes footgun: undeclared argtypes/restype makes the wait silently never fire

The first prototype run watched two ancestors that then died, yet never
fired: without explicit `restype = wt.HANDLE` on `OpenProcess` and
`argtypes` on `WaitForMultipleObjects`, ctypes' default int conversions
break the call silently (the waiting thread errors or waits on garbage).
The implementation must declare full `argtypes`/`restype` for every
kernel32 function it binds, and the regression test must cover the
fires-on-death path end-to-end in a real subprocess, not just import-check
the module.

Source: scratchpad `watchdog_proto.py` failure run vs. isolated success
run, 2026-07-17.

### L6 - Design implication: watch the whole ancestor chain, not one PID

Combining L2-L5: the worker must treat "any ancestor between me and my
spawning client has died" as termination intent. Taking `SYNCHRONIZE` process
handles on each ancestor at startup (before any PID reuse is possible) and
waiting on them from a daemon thread covers both leak modes: client death
(ancestor = client) and kill-the-direct-child reconnects (ancestor = uv.exe /
launcher). stdin EOF remains the primary, protocol-blessed exit path (L3);
the watchdog is a backstop, so its trigger action must be an unconditional
hard exit that cannot hang on a wedged event loop.

A static `--parent-pid` flag in the seeded MCP config cannot carry the
client's pid (the config is written at install time), so ancestor discovery
at startup is the practical route to the LSP-style contract; an optional
`--parent-pid` override remains cheap to accept for clients that can pass
one. Per S2, the watchdog's trigger action must be `os._exit`, not a
graceful loop shutdown.

Source: synthesis of L2-L5 and S1-S6.

## Sources

Evidence gap: the retained document body has no separately labelled Sources section.
