---
tags:
  - '#audit'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
related: []
---

# `mcp-stdio-lifetime` audit: `stdio lifetime watchdog implementation review`

## Scope

Review of the full mcp-stdio-lifetime execution (P01-P03, S01-S08) against
the ADR and research: the ctypes watchdog module
(`src/vaultspec_rag/server/_stdio_lifetime.py`), entry-point wiring
(`server/_main.py`), config registration, the three test surfaces, and the
docs. Dimensions: ctypes correctness, concurrency/lifetime,
ADR conformance, test integrity, security, project-rule compliance.
Verdict: PASS - no critical or high findings; unit (22), regression, and
e2e chain-kill suites verified green during review.

## Findings

### grace-window-disarm | medium | Early client death inside the grace window permanently disarms the backstop

If every real ancestor dies within the startup grace window, the prune
empties the survivor set and the watchdog disarms for the process
lifetime - the orphan-leak shape compressed into startup. Accepted
residual risk already recorded in the ADR Consequences; resolution is a
docstring note in the module so the empty-survivors disarm is not
mistaken for a bug. RESOLVED: docstring note added post-review.

### disarm-handle-leak | low | Wait-failure and install-failure paths leaked SYNCHRONIZE handles

The wait-failure disarm branch returned without closing survivor handles,
and an install failure after handle acquisition leaked the watched set
(bounded at ~9 handles for the process lifetime). RESOLVED: both paths
now close handles post-review.

### hand-built-json | low | The stderr exit line hand-built its JSON

The exit line interpolated the ancestor exe name into an f-string JSON
literal; safe in practice (Win32 image basenames cannot carry quotes or
control characters) but resting on an unstated invariant. RESOLVED:
switched to `json.dumps` post-review.

### adr-name-in-comment | low | Config comment names the ADR

`config.py`'s new knob comment references the ADR by name, matching the
file's pervasive existing convention. ACCEPTED: left as-is; a file-wide
metadata cleanup is out of scope.

### posix-pid-reuse | low | POSIX explicit parent-pid poll cannot detect PID reuse

`os.kill(pid, 0)` reads a reused PID as alive, so an explicit POSIX
target may never fire. ACCEPTED: the Windows path (the platform where the
leak manifests) is race-free via startup handles; the POSIX poll is the
documented coarse fallback.

## Recommendations

- Ship as-is after the three post-review fixes (docstring note, handle
  close on disarm paths, `json.dumps`); no revision cycle required.
- Apply the same reference design to the companion repo's
  `vaultspec_core.mcp_server.app` (tracked as vaultspec-core issue 220).
- Re-check upstream python-sdk 2233/2365 before acting on issue 184.
