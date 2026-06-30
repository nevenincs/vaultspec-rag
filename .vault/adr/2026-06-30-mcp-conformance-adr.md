---
tags:
  - '#adr'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-mcp-conformance-research]]"
  - "[[2026-06-30-mcp-conformance-reference]]"
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-06-24-service-hardware-singleton-adr]]"
  - "[[2026-06-24-service-discovery-schema-adr]]"
  - "[[2026-06-27-rag-broker-affordances-adr]]"
---

# `mcp-conformance` adr: `MCP service-discovery on the machine-singleton model` | (**status:** `accepted`)

## Problem Statement

An agent reached for MCP to search the project it was standing in and got an answer about
a different project: the MCP `get_service_state` reported a live service with an unrelated
project loaded and a zero count for the caller's own root. The grounding research traced
this to service discovery. Both the CLI and the MCP resolve which service to talk to
through one helper that reads a `service.json` in the process's own status directory
(`VAULTSPEC_RAG_STATUS_DIR`, else the default). The CLI is short-lived and re-resolves
each invocation; the MCP is a long-lived process that freezes its config singleton at
first call, binding it for its whole lifetime to whatever status directory it was spawned
under. A passed `project_root` only scopes which project the chosen daemon answers about -
it never re-selects which daemon. So a flag-less CLI search resolves the live service
while the MCP, frozen to a foreign status directory, cannot. Meanwhile a machine-global
discovery pointer that was added precisely to let a consumer find the one running service
ships only its write half - the daemon writes it on every heartbeat, but nothing reads it.
This ADR decides the discovery contract that makes the MCP (and any consumer) resolve the
one running machine service exactly as a flag-less CLI command does. It is the connection
half of the MCP conformance epic; the companion scope ADR decides what the MCP surface is.

## Considerations

The load-bearing architectural fact, confirmed in the code: the resident service is a
**machine singleton** enforced by an OS advisory lock anchored to the machine-global
managed-storage directory, held for the daemon's lifetime, with `server start`
pre-flight-refusing when a live holder exists. Because the lock is status-directory
independent, two live daemons cannot coexist on one machine - the second start is refused.
This collapses the ambiguity the research flagged: the transcript symptom was not a
*wrong* daemon reached through a foreign status directory (two daemons are impossible),
but the *one* machine daemon that simply had not yet indexed the caller's project, reached
or not reached depending on which status directory the consumer happened to read. The
defect is therefore **discoverability across status directories**, not daemon selection.

That reframes the fix. Two directions were considered. Project-aware multi-daemon
selection - letting `project_root` choose among several daemons - is rejected: it
contradicts the machine-singleton invariant, there is only ever one daemon. The chosen
direction is to make discovery resolve *the* one machine service through machine-global
state that every consumer shares regardless of its status directory: the OS lock for
liveness, and the machine-global pointer for the address. The pointer's write half already
ships; this ADR wires the read half and the validation around it. Local mode remains a
force-gated explicit opt-out, never a silent fallback.

## Constraints

This ADR builds directly on three accepted decisions and must not contradict them: the
machine-singleton service model, the service-discovery schema (the versioned
`service.json` payload with heartbeat and staleness fields), and the broker-affordances
work that introduced the machine-global pointer and idempotent JSON start. It depends on
the OS-lock liveness probe remaining side-effect-free for a client to call (it is designed
so: acquire-then-immediately-release without disturbing a real holder). The discovery
resolution must not reintroduce a dependency on the per-instance status directory, or the
frozen-singleton bug returns by another route. The machine-global anchor is the managed
Qdrant storage directory; if that anchor is overridden inconsistently across consumers
(the test-isolation case), discovery can still diverge - so this ADR is coupled to the
existing managed-storage-isolation discipline. The infrastructure confounds (server-mode
Qdrant instability, CPU-only torch) are out of scope: this ADR governs how MCP behaves
given the backend state, not backend stability.

## Implementation

Discovery is re-centred on machine-global state, expressed as the following decisions.

- **SD1 - The machine-global pointer is the authoritative address; the OS lock is the
  liveness authority; staleness validates.** Service resolution consults the
  machine-global discovery pointer (anchored beside the machine lock, status-directory
  independent) for the live service's port and token, and treats the OS advisory lock's
  live holder as the authority for whether a resident service exists at all. A candidate
  pointer is accepted only when it validates: its heartbeat is fresh within the schema's
  staleness window and it corresponds to a live lock holder. The per-status-directory
  `service.json` is demoted to a compatibility hint that never overrides a valid
  machine-global resolution. This is deliberately *authoritative*, not an absent-only
  fallback: a stale or foreign per-status-directory file present on disk must not win over
  the live machine service.

- **SD2 - One machine service; discoverability, not selection, is the fix.** The contract
  assumes and preserves the machine-singleton invariant: exactly one resident daemon,
  multi-tenant across projects. Project-aware multi-daemon selection is rejected.
  Resolving the single service through machine-global state is the whole fix; `project_root`
  remains only the scope of the answer, as today.

- **SD3 - Resolution is status-directory independent and re-resolved per call.** Because
  the pointer and lock are anchored to the machine-global managed-storage directory -
  identical for every consumer on the machine - resolving through them does not depend on
  the per-instance status directory the long-lived MCP froze at spawn. Discovery is
  re-read per call (a cheap file read plus the lock probe), so a service that starts,
  stops, or restarts after the MCP process began is still resolved correctly.

- **SD4 - Stale managed-state is detected and refused.** The staleness validation in SD1
  is what protects against the orphaned pointer the research found on the live box (a dead
  pid, a days-old heartbeat, and a leaked token in the real managed directory): an
  unvalidated stale pointer is treated as absence, not as a live service. Clean shutdown
  continues to unlink the pointer. The leaked test token in the real managed directory is a
  test-isolation hygiene defect to fix alongside, under the existing managed-storage
  isolation discipline.

- **SD5 - Resolution and transport errors are legible.** On failure the resolution and
  transport layer reports what it resolved and why it failed: which discovery source it
  consulted, whether a live lock holder exists, the resolved port, and the failure class
  (no live service, versus unreachable, versus authentication). This replaces the
  empty-bodied HTTP error and the port confusion the research recorded.

- **SD6 - An absent service fails fast with a legible remediation.** When no live machine
  service resolves, every MCP tool fails fast - no retries, no silent partial answer, no
  degraded fallback - with one actionable error instructing the operator to start the
  service (`vaultspec-rag server start`). For the MCP this is surfaced as a tool result
  marked in error (the spec's mechanism for a recoverable, self-correctable failure) rather
  than a protocol fault. The honest fast failure is the cure for the transcript's silent
  dead end; the MCP does not gain lifecycle powers to "fix" an absent service itself.

## Rationale

The fix follows from the code the research grounded. The OS lock is the real authority for
"is a service running on this machine", and it is status-directory independent - so
liveness should be read from it, not inferred from a status-directory file the MCP may have
frozen onto the wrong directory. The machine-global pointer was built for exactly this
cross-status-directory discovery but left unread; wiring its read half, gated by lock
liveness and heartbeat staleness, delivers its stated purpose and resolves the symptom
without inventing a new mechanism. Making resolution authoritative rather than absent-only
is what fixes the observed case, where a foreign status directory still held a present
(but irrelevant) `service.json`. Failing fast and legibly is grounded in the MCP spec's
guidance that recoverable failures carry actionable feedback, and in the epic mandate that
the MCP must not silently degrade.

## Consequences

The MCP and the CLI converge on the one machine service with no port flags, from any
status directory, which is the behaviour the mandate requires. The previously write-only
machine pointer becomes load-bearing, so its schema and heartbeat cadence now matter to
correctness, not just observability - a coupling to maintain. Staleness validation means a
crashed daemon's lingering pointer no longer misleads a consumer, closing the stale-state
misdirection the research found. The honest fail-fast contract replaces a silent dead end
with a one-line remediation. Risks: the lock probe adds a small per-call cost (a file open
and a non-blocking lock attempt) that must stay genuinely side-effect-free on both
platforms; and the machine-global anchor must be isolated consistently in tests, or
discovery can diverge under an overridden storage directory - which is why this ADR leans
on the managed-storage isolation discipline. This contract is the foundation the scope
ADR's surviving tools stand on; the two are approved together or not at all.

## Codification candidates

- **Rule slug:** `service-discovery-resolves-the-machine-singleton`.
  **Rule:** Client service discovery must resolve the one resident machine service through
  the status-directory-independent machine-global pointer, validated by the OS-lock live
  holder and the heartbeat staleness window, never trusting a per-status-directory
  `service.json` that names a stale or dead service; when no live service resolves, fail
  fast with the start-the-service remediation rather than falling back silently.
