---
tags:
  - '#adr'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
related:
  - "[[2026-06-12-qdrant-server-provisioning-research]]"
  - "[[2026-06-12-serving-runtime-research]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-05-qdrant-performance-adr]]"
---

# `qdrant-server-provisioning` adr: `qdrant server mode with binary provisioning` | (**status:** `accepted`)

## Problem Statement

Every saturation benchmark on the 6.3 GB corpus chokes on `QdrantLocal`, the
pure-Python local engine: 149 s mean search scans, O(N^2) GIL-pinned id scrolls, a
linear SPLADE scan over ~114k chunks, and zero read concurrency within a collection.
The serving-runtime research concluded the fix is not a language rewrite but swapping
the toy engine for the real Rust `qdrant` server, which the store already supports
behind the `qdrant_url` seam with no point-operation locks. What is missing is the
operational machinery: obtaining the binary safely, supervising it as a child of the
resident daemon, namespacing collections so one server serves many roots, and
exposing the whole thing through the CLI without breaking the zero-dependency local
default.

## Considerations

- Distribution options compared in the sibling research: bundling in platform wheels
  (six-wheel matrix, ~30 MB each, redistribution obligations - rejected), system
  package managers (no version pin, weakest on Windows - rejected), a companion PyPI
  binary package (none exists; we would own the release engineering - rejected), and
  download-on-first-use with a committed pin + SHA256 (no wheel impact, exact pin in
  reviewed code - selected).
- Topology: one shared local qdrant server with per-root namespaced collections
  versus one process per root. The resident service is already multi-tenant with a
  16-slot registry; per-root processes would mean per-root ports, supervision state,
  and eviction races for no isolation benefit. Shared server selected.
- The locked qdrant-client is 1.18.0; the latest server release is v1.18.2 on the
  same minor line. Client/server minor alignment is the compatibility contract.
- The repo already has the exact precedents to mirror: the cu130 pinned-constants
  package for version pinning, the daemon spawn/terminate helpers for supervision,
  and the install command's sync-vocabulary + dry-run UX for the provisioning verb.
- Local mode must remain the zero-dependency default; server mode is opt-in per
  service start.

## Constraints

- The per-collection backend-aware store locking from the service-concurrency ADR is
  the load-bearing parent: server-mode stores already take no point-operation locks.
  That decision is accepted and landed on this branch.
- Never silently download: provisioning is an explicit verb or an explicitly
  consented flag on `server start`. Checksum verification precedes extraction and
  execution; mismatch is a hard failure that deletes the partial download.
- HTTPS only, host-pinned to `github.com` / `objects.githubusercontent.com`;
  cross-host redirects rejected.
- Loopback binding always; the existing API-key plumbing remains the remote-server
  escape hatch.
- Daemon inherits configuration only through the environment: every new knob is a
  `VAULTSPEC_RAG_*` env var with CLI translation.
- No background sweeper threads: qdrant liveness rides the existing heartbeat loop.
- Tests are real-binary/real-GPU/real-server; no mocks, skips, or fakes.
- On Windows, breakaway flags alone cannot guarantee child reaping; a Job Object
  with kill-on-close is required so a hard daemon death can never orphan a server.

## Implementation

A new runtime package owns everything qdrant-server: a constants module pinning the
server version (1.18.2) and the per-asset SHA256 map for all six release assets
(mirroring the cu130 pinning constants); an asset-resolution module mapping
platform/arch to the release asset and resolving the active binary in the order
operator env var, provisioned managed dir, PATH; a provisioning module that
downloads host-pinned over HTTPS, verifies SHA256 before extraction, extracts,
marks executable, writes a manifest, and reports in the install command's sync
vocabulary with full dry-run support; and a supervision module that spawns the
loopback-bound child with storage and ports injected via `QDRANT__*` env vars,
polls the readiness endpoint with backoff, terminates gracefully, and on Windows
assigns the child to a kill-on-close Job Object.

Configuration gains four knobs: server-mode toggle (default off), qdrant HTTP port
(default 8765, one below the service port), operator binary path, and the shared
storage dir (default under the managed service directory, multi-root).

In server mode the store derives a stable per-root collection prefix from a short
hash of the resolved root path; the existing collection names remain as suffixes
and local-mode names are unchanged. The service lifespan spawns qdrant before model
load, publishes the in-process server URL so registry stores open server-mode, adds
a qdrant block to the health payload and the service-state surface, records the
child PID in the service status file, and stops qdrant last among data components
on shutdown. The heartbeat loop gains a qdrant liveness check with one bounded
auto-restart, surfacing degraded state otherwise.

The CLI gains a `server qdrant` group (`install` with upgrade/dry-run/json,
bounded `status`, gated `clean`) and `server start` gains `--qdrant` plus an
explicit auto-provision consent flag; an absent binary without consent prints the
exact install command and exits non-zero.

## Rationale

The serving-runtime research attributes the measured saturation collapse to
`QdrantLocal` specifically: the same product in server mode is a Rust engine with
HNSW, a sparse inverted index, payload pushdown, and concurrent reads, reachable
through an env var the store already honors. Download-on-first-use with a committed
SHA256 pin keeps the PyPI wheel pure-Python, keeps the pin in reviewed code, avoids
redistribution obligations, and is idempotent and offline-tolerant after first
fetch. One shared server with namespaced collections matches the registry's
existing multi-tenancy instead of multiplying supervision state. Every mechanism
chosen here reuses an existing, audited pattern in this codebase rather than
inventing a new one.

## Consequences

- Large-corpus and multi-agent deployments get the Rust engine's concurrency and
  index structures; the hard residual from the concurrency ADR (local-mode
  same-collection serialization) disappears in server mode.
- First server-mode start requires either a one-time ~29 MB download (explicitly
  consented) or an operator-supplied binary; air-gapped setups use the env-var
  escape hatch.
- The daemon now supervises a child process: liveness, restart, and shutdown
  ordering become part of the service's operability surface and are mirrored across
  health, status, and state outputs.
- Version bumps are a two-line constants edit plus a re-run of the install verb; a
  regression test pins the server minor to the locked client minor so they cannot
  drift silently.
- Local mode keeps its per-project on-disk store and behavior unchanged; server
  storage is shared and lives under the managed service directory, so cleaning a
  project's data dir no longer removes its server-mode collections (the `clean`
  surface documents this).

## Codification candidates

- **Rule slug:** `pinned-binaries-verify-before-execute`.
  **Rule:** Any externally fetched executable must be pinned to a committed version
  and SHA256 constant, verified before extraction and before first execution, with
  checksum mismatch deleting the partial artifact and failing hard.
