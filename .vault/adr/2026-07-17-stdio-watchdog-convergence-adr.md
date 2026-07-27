---
tags:
  - '#adr'
  - '#stdio-watchdog-convergence'
date: '2026-07-17'
modified: '2026-07-27'
related:
  - "[[2026-07-17-stdio-watchdog-convergence-research]]"
  - '[[2026-07-17-stdio-watchdog-convergence-audit]]'
---

# `stdio-watchdog-convergence` adr: `pipe-creator primary anchor and the functional assertion floor` | (**status:** `accepted`)

## Problem Statement

Rag and core shipped sibling stdio lifetime watchdogs with different
primary anchors, and a cross-repo parity review (issues 229/232) found one
precision gap in rag's ancestor-chain design - the death of a process above
the client reaps a live session - and one testing gap: rag's e2e tests
assert process existence, never served MCP capability. Core has adopted the
converged watchdog design and the functional assertion floor; this ADR
binds rag to both so the two watchdogs differ only in nothing.

## Considerations

- Anonymous pipes are named pipes on Windows: `GetNamedPipeServerProcessId`
  on inherited stdin identifies the exact client at any wrapper depth, with
  no depth bound or grace heuristics (research C1).
- The layered composition (explicit override, resolved client, chain
  fallback only when the client does not resolve) fixes the above-client
  false reap and the client-died-during-grace disarm in one move (C2, C3).
- The exit event shape is already shared between the repos for host
  tooling; the convergence must preserve it byte-compatible.
- The mcp stdio transport is line-delimited JSON-RPC, so a wire-level test
  harness is a few dozen lines of stdlib subprocess code - no client SDK
  needed (C5).
- The rules binding the module stay: stdlib-only, no mcp or torch imports,
  stdio-branch-only install, fail-open arming.

## Considered options

- **Keep ancestor-chain primary, add the client as one more target:**
  rejected - keeps the above-client false-reap topology; the chain must not
  be armed when the exact client is known.
- **Adopt core's module verbatim (import or vendor):** rejected - crosses
  the repo boundary the enrollment architecture keeps one-way; rag
  implements under its own record (the A4 and stdio-lifetime precedent).
- **SDK-based test client for the wire tests:** rejected - the mcp client
  SDK drags pywin32 into test paths and hides the wire; raw line-delimited
  JSON-RPC over the subprocess pipes asserts the actual transport.
- **Chosen:** port the layered-anchor design into `_stdio_lifetime.py`
  (resolver, grace-prunable flag, client-instead-of-chain composition), and
  raise every real-shim-spawning test to the functional floor with a stdlib
  wire harness; the client-kill scenario composes both.

## Constraints

- `WatchedAncestor` gains semantics (`grace_prunable`); existing unit tests
  that enumerate the chain keep passing via default behavior.
- The chain-kill e2e must move from a synthetic watchdog-only worker to a
  real serving shim without losing determinism; the intermediary-client
  shape (C6) provides it because precise anchors skip the grace window.
- POSIX behavior is unchanged (reparent poll); `resolve_stdin_client_pid`
  returns `None` there by contract.

## Implementation

`_stdio_lifetime.py` gains `resolve_stdin_client_pid()` (msvcrt stdin
handle to `GetNamedPipeServerProcessId`, fail-open), a `grace_prunable`
flag on watched targets, and a reworked installer: explicit `--parent-pid`
first (precise), then the resolved client (precise); the discovered chain
arms ONLY when no client resolved; the wait thread sleeps the grace window
only when prunable targets exist, never prunes precise anchors, and closes
handles on every disarm path. The e2e suite gains a stdlib line-JSON wire
harness; the EOF test performs the handshake and asserts the five-tool
surface before closing stdin; the client-kill test proves a served
tools/list through an intermediary client and instant reap on its death; a
degraded-mode tool call asserts the daemon-unreachable guidance arrives
through the wire. Docs update the lifetime section with the anchor
layering.

## Rationale

Research C1-C6; behavior converges with core's shipped watchdog while the
implementation stays repo-local, and the functional floor turns both
lifetime tests into capability proofs, closing 229 and 232 together.

## Consequences

- The terminal-dies-while-client-survives topology no longer reaps live
  sessions; an already-dead client reaps instantly instead of disarming.
- The e2e suite now fails if the shim stops serving, not merely if it stops
  existing; wire framing changes upstream would surface here first.
- The synthetic watchdog-only worker test is superseded by the real-shim
  client-kill scenario.
