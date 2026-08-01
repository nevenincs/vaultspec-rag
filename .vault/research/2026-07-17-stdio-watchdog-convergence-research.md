---
tags:
  - '#research'
  - '#stdio-watchdog-convergence'
date: '2026-07-17'
modified: '2026-07-27'
body_hash: 'sha256:d824a0a86d6738512f91dd502f77a30499e1225abb0e11fdc5e10f71af10dacd'
related: []
---

# `stdio-watchdog-convergence` research: `pipe-creator anchor and the functional assertion floor`

Grounding for issues 229 and 232, both cross-repo parity handovers from the
core team after both repos shipped stdio lifetime watchdogs on 2026-07-17.
Reference implementation read in full: `vaultspec_core/mcp_server/watchdog.py`
on core main (0.1.48), plus core's functional-assertion-floor test work
(core PR 226) and the `2026-07-17-mcp-static-launch-adr` A4 sibling contract
(whose rag-side seed items shipped in rag 0.3.1 - verified addressed).

## Findings

### C1 - The pipe-creator anchor identifies the exact client at any wrapper depth

Windows anonymous pipes are named pipes underneath, so
`GetNamedPipeServerProcessId` on the inherited stdin handle resolves the
process that created the pipe - the MCP client itself - regardless of how
many `uv`/launcher wrappers sit between. Core's `resolve_stdin_client_pid`
fails open (`None`) for console/redirected stdin, unresolvable handles, or
a self/zero PID.

### C2 - Our ancestor-chain-only design has one real false-reap topology

Watching every ancestor treats the death of processes ABOVE the client
(terminal, tmux, host shell) as termination intent; a client that detaches
and survives its terminal gets its live session reaped. Core's composition
fixes this: when the client anchor resolves, ONLY the explicit override and
the client are watched - the chain is not armed at all; the chain remains
the fallback for launches where stdin is not a client-created pipe.

### C3 - Precise anchors are never grace-pruned; that also fixes instant reap

Core marks the resolved client and the explicit `--parent-pid` override
grace-unprunable: no grace sleep when only precise anchors are watched, and
an already-dead client signals exit immediately (a dead process handle is
signaled, so wait-any returns at once). Our current design grace-prunes
everything, so a client that dies inside the first 10s silently disarms the
backstop - the accepted residual risk in the stdio-lifetime ADR now has a
clean fix.

### C4 - Remaining deltas are hygiene we already partly share

Core closes handles on the wait-failure disarm branch and on thread-start
failure (we adopted both post-review), skips the grace sleep when nothing
is prunable, and emits the identical `stdio_watchdog_exit` JSON event shape
(deliberately, for shared host tooling). Kill-switch env names stay
per-package (`VAULTSPEC_STDIO_WATCHDOG` vs `VAULTSPEC_RAG_STDIO_WATCHDOG`).

### C5 - The functional assertion floor: existence is not capability

Issue 232's inventory is accurate: rag's conformance tests assert the
five-tool surface in-process, and both e2e lifetime tests assert
liveness/exit codes only - no test drives the initialize handshake,
tools/list, and a tool call over a spawned shim's real stdio transport. The
mcp stdio transport frames one JSON-RPC message per line, so a wire harness
needs no LSP-style framing. The floor (mirroring core's adopted contract):
every test that spawns the real shim asserts at least one served
capability - handshake identity, the exact five-tool surface, or one
structurally-asserted tool result through the wire (e.g. `search_vault`
degraded-mode guidance with the daemon unreachable).

### C6 - The client-kill shape composes both issues into one test

An intermediary client script that spawns the real shim over pipes,
performs the handshake and tools/list itself, reports success, then idles -
with the test killing the intermediary - proves served capability (232) and
exact-client instant reap through the pipe-creator anchor (229, no grace
wait since the anchor is precise) in a single real-process scenario.

## Sources

Evidence gap: the retained document body has no separately labelled Sources section.
