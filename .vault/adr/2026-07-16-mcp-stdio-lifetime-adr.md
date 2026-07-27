---
tags:
  - '#adr'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-27'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-research]]"
  - '[[2026-07-16-mcp-stdio-lifetime-audit]]'
---

# `mcp-stdio-lifetime` adr: `The stdio shim owns its lifetime: ancestor-chain watchdog behind stdin EOF` | (**status:** `accepted`)

## Problem Statement

The stdio MCP shim (`vaultspec-search-mcp`, and the plain `uv run`/`uvx`
spawn shapes agents use) never exits when the client that spawned it dies or
abandons it. Over ~2 days of normal agent usage on Windows, 8 logical shims
(~24+ OS processes) accumulated as orphaned `uv.exe -> launcher -> python`
chains, each holding a connection against the single-seat backend and
degrading the host. The grounding research reproduced the mechanism: the
shim's only exit path is stdin EOF, EOF handling itself works, but agent
clients abandon old generations while alive (or kill only the direct child
`uv.exe`, which orphans the worker with its stdio intact), so EOF never
arrives and the anyio stdin reader blocks a non-daemon thread forever. The
shim currently has no backstop. This ADR decides the server-side lifetime
contract for the stdio shim.

## Considerations

- The blocked stdin read cannot be cancelled or timed out in-process: anyio
  offloads `readline` to a non-daemon worker thread without
  `abandon_on_cancel`, so the only reliable backstop action is hard process
  death (`os._exit`), a pattern the codebase already uses to free the store
  lock in the service-first search fallback (research S1/S2).
- Both leak modes must be covered: (a) the client dies but the pipe write
  end survives; (b) the client stays alive and abandons or kills the chain -
  the dominant mode in the live audit (research L2, L5). A watchdog on one
  fixed PID covers only one of the two; the severed link can be anywhere in
  the ancestor chain.
- Client-side fixes are out of our hands: Claude Code and Codex are not
  Python-SDK clients (the SDK's job-object kill is client-side machinery),
  and uv's 0.9.28 job-object fix covers only the uvx-wrapper-to-uv link
  (research S3/S4). Ecosystem consensus (context7 PR 2576, LSP 3.17
  `processId` contract) is that stdio servers defend themselves (S6).
- The shim is bound by the `2026-06-18-mcp-service-client-adr` (thin,
  torch-free client) and `2026-06-30-mcp-optional-dependency-adr` (`mcp` is
  optional): the watchdog must be stdlib-only (ctypes on Windows), must not
  import `mcp`, torch, or the store, and must not run in the HTTP daemon,
  which is a deliberately detached long-lived service.
- The seeded MCP config is static JSON written at install time, so it cannot
  carry the client's PID; an LSP-style `processId` handshake is not part of
  the MCP spec. Ancestor discovery at startup is the only self-serve way to
  learn whom to watch (research L6).
- Feasibility is proven: Toolhelp32 ancestor walk + `OpenProcess(SYNCHRONIZE)`
  - wait-on-handle all work unprivileged from ctypes; handles taken at
    startup defuse PID reuse, and creation-time monotonicity guards the walk
    itself (research W1). Undeclared ctypes signatures fail silently, so the
    implementation and its tests must exercise the fires-on-death path
    end-to-end (W2).

## Considered options

- **Do nothing / wait for upstream (clients, uv, mcp SDK):** rejected - the
  leak is live today, every upstream fix covers a different link, and
  ecosystem consensus is server-side self-defense.
- **Harden stdin handling (read timeout / cancellation):** rejected -
  impossible in-process against a blocked non-daemon anyio reader (S2).
- **Idle timeout (exit after N minutes without requests):** rejected - agent
  sessions legitimately idle for hours; any threshold either kills live
  sessions or leaves orphans for hours.
- **Require a client-passed `--parent-pid` (LSP style):** rejected as the
  sole mechanism - the install-time config cannot know the PID and no major
  client passes one; kept as an optional override for spawners that can.
- **Job object tied to the client:** rejected - only the client can place
  the child in a kill-on-close job; the child cannot tie itself to a
  process it does not control.
- **uv version floor >= 0.9.28:** rejected as a fix - repro L5 leaked on uv
  0.11.29; noted as unrelated-to-us defense in depth.
- **Ancestor-chain watchdog with hard-exit backstop (chosen):** watch every
  startup-live ancestor; any death = termination intent; `os._exit`.

## Constraints

- Windows-first: the handle-wait watchdog is ctypes/kernel32 and ships for
  `win32` only; POSIX gets a cheap orphan poll (`os.getppid()` reparenting
  check). No new dependencies, no pywin32 (its eager-import problem is the
  subject of open upstream python-sdk#2233; issue #184 stays blocked).
- The watchdog must be inert on every non-stdio path: HTTP daemon mode,
  `--help`, and the CLI must never install it (the daemon outliving its
  spawner is by design - `_service_lifecycle` owns daemon lifetime).
- Spawn-helper false positives: a transient wrapper (e.g. `cmd /c`) that
  legitimately exits seconds after spawning the chain must not kill a live
  session. The watchdog arms after a short startup grace and drops ancestors
  that died during the grace window.
- Thin-client discipline (parent ADRs above) is stable and load-bearing:
  the new module must stay stdlib-only and import-light so the
  fresh-interpreter import-graph regression tests keep holding.

## Implementation

A new stdlib-only module `src/vaultspec_rag/server/_stdio_lifetime.py`
provides `install_stdio_lifetime_watchdog()`:

- At stdio-mode startup (`server/_main.py` stdio branch, before `mcp.run`),
  discover the ancestor chain with a Toolhelp32 snapshot walk (bounded
  depth, cycle-safe, creation-time monotonicity as the PID-reuse guard) and
  immediately open `SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION`
  handles on every live ancestor. Every kernel32 binding declares full
  `argtypes`/`restype`.
- After a short grace period, close handles of ancestors that already
  exited (spawn helpers) and arm a daemon watchdog thread on the survivors
  via wait-any `WaitForMultipleObjects` (infinite timeout).
- On any watched ancestor's death: log a single structured line to stderr
  naming the dead ancestor, then `os._exit(0)`. Exit code 0 - the shim
  terminated on purpose; a non-zero code would make supervising brokers
  misread a clean reap as a crash.
- An optional `--parent-pid` argument on the console script adds an
  explicit watch target ahead of discovery (LSP-style override). An env
  knob (`VAULTSPEC_RAG_STDIO_WATCHDOG=0`) disables the watchdog entirely as
  the operator escape hatch.
- POSIX fallback: a daemon thread polls for reparenting
  (`os.getppid()` changed / init) at a coarse interval and takes the same
  exit path. stdin EOF remains the primary, protocol-blessed shutdown on
  all platforms; the watchdog is strictly a backstop.
- Tests: unit coverage for the ancestor walk and guards; an integration
  test that spawns a real chain, kills a middle process, and asserts the
  worker exits (the W2 end-to-end mandate); regression guards that the
  module imports neither `mcp` nor torch and that the HTTP daemon path
  never installs the watchdog.

## Rationale

Research L3/L4 proved the EOF path and chain reap already work when the
client behaves, so the design keeps EOF primary and adds the smallest
backstop that covers both observed leak modes. Watching the whole ancestor
chain is the key move: the severed link in the dominant abandon/kill mode
(L2, L5) is `uv.exe` or the launcher, not the client, so any-ancestor-death
is the correct termination-intent signal, and handles taken at startup make
it race-free against PID reuse (W1). Hard exit is forced by S2 - nothing
softer can unwedge the reader - and precedent (S6) confirms server-side
self-defense is the ecosystem norm. The design honors the standing
thin-client and optional-`mcp` ADRs by staying stdlib-only, stdio-only.

## Consequences

- Orphaned shim chains self-reap within moments of the chain breaking; the
  dozens-of-pythons pile-up and the phantom load on the single-seat backend
  stop accumulating. `uv run`/`uvx` spawn shapes get the fix for free since
  the watchdog lives in the worker process itself.
- A deliberately killed intermediate (operator kills `uv.exe` but wants the
  worker alive) now takes the worker down - accepted: that intent has no
  legitimate use, and the env knob remains for exotic setups.
- Residual risk: a spawner whose intermediate exits *after* the grace
  window would false-positive; no observed spawn shape does this (all live
  chains audited were stable), and the structured stderr line plus env knob
  make it diagnosable and escapable.
- The vaultspec-core half of the report (`vaultspec_core.mcp_server.app`)
  is out of scope here and needs the same treatment in the companion repo;
  this ADR is the reference design for it.
- Upstream follow-ups stay open: issue #184 remains blocked on
  python-sdk#2233; a uv floor is not required.
