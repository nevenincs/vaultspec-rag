---
tags:
  - '#research'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
related:
  - "[[2026-06-12-serving-runtime-research]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-05-qdrant-performance-adr]]"
---

# `qdrant-server-provisioning` research: `qdrant binary provisioning and release pipeline`

Implementation design for shipping vaultspec-rag with the Qdrant server binary - the
approved promotion of server mode to the recommended topology for large corpora and
multi-agent serving. Covers binary distribution, version pinning against
qdrant-client, process topology and supervision, release-pipeline and install UX
changes, and the security model. Grounded in the repository's existing precedents:
the install command's CUDA-wheel provisioning, the daemon supervision machinery, and
the release-please/publish flow.

## Findings

### Executive recommendation

Primary path: download-on-first-use provisioning into a managed bin dir
(`~/.vaultspec-rag/bin/qdrant/<version>/`) from upstream GitHub releases, version
pinned with a committed SHA256 constant, fetched by an explicit
`vaultspec-rag server qdrant install` verb and offered (never silently executed) on
first server-mode start. This keeps local mode the zero-dependency default, keeps the
PyPI wheel pure-Python, is idempotent and offline-tolerant after first fetch, and
reuses the exact patterns the codebase already has (the consumer-mutation install UX
with sync vocabulary and dry-run, plus the daemon spawn/terminate helpers).

Fallback: operator-supplied binary via a new `VAULTSPEC_RAG_QDRANT_BINARY` env var
(air-gapped/proxy/policy escape hatch), with PATH detection as a convenience. Docker
remains optional, never required.

Rejected: bundling the binary in platform wheels (six-wheel matrix, redistribution
obligations, bloats every default install); hard dependence on system package
managers (no version pin, weakest on Windows); a companion binary PyPI package (none
exists or is maintained as of 2026-06-12, and authoring one is strictly more release
engineering for no benefit).

Confirmed grounding facts: Qdrant ships per-platform release binaries (~28-31 MB
each; Windows zip contains a single `qdrant.exe`) with SHA256 digests embedded in
the release JSON; latest is v1.18.2; the locked qdrant-client is 1.18.0; the store
already has a complete server-mode seam behind `qdrant_url` and takes no
point-operation locks in server mode - no business-logic change is needed.

### Distribution options compared

- Download-on-first-use, pinned + sha256-verified: no wheel impact, exact pin in
  reviewed code, no redistribution obligations. PRIMARY.
- Republish in platform wheels: forces a cibuildwheel matrix, ~30 MB per wheel,
  Apache-2.0 notice bundling, bloats installs whose default mode needs no server.
  Rejected.
- User-managed package managers (winget/scoop/choco/brew): no uniform version pin;
  kept only as detection inside the fallback. Rejected as primary.
- Companion PyPI binary package: nothing maintained exists; we would own both the
  pin and redistribution. Rejected.

Provisioning mechanics: resolve the asset for the current platform/arch, download
over HTTPS host-pinned to github.com (reject cross-host redirects), verify SHA256
against the committed constant before extraction, extract and mark executable,
write a provisioning manifest. If the verified binary already exists the verb
reports `unchanged` with no network I/O.

### Version pinning and compatibility

The pin lives in code: a constants module in the new runtime package carrying the
server version plus a per-asset SHA256 map - mirroring the existing CUDA torch
pinning constants. Pin the server to the same minor line as the locked
qdrant-client (client 1.18.0 - server 1.18.2). A startup check compares the
installed client minor against the pinned server minor and logs a structured
warning beyond one minor of skew. Upgrades are a two-line constants edit plus
`server qdrant install --upgrade`; a regression test asserts the pinned minor
matches the locked client minor so the two cannot drift silently.

### Lifecycle integration

Topology decision: one shared local Qdrant server with namespaced collections per
root (a per-root collection prefix on the existing vault/code collection pair) -
NOT one process per root. The resident service is already multi-tenant with a
16-slot registry; per-root server processes would mean per-root ports, supervision
state, and eviction races for no isolation benefit worth the cost.

Supervision reuses the daemon machinery: spawn with the same process-group flags
and log redirection; record the child PID in the service status file; poll the
server's readiness endpoint with the existing backoff loop; bind loopback only,
default port one below the HTTP service's. On Windows, assign the qdrant child to
a real Job Object with kill-on-close so a hard daemon death can never orphan a
server process (the repo currently uses only breakaway flags; this adds the
guarantee). Shutdown ordering: watchers, then stores (release client connections),
then the qdrant child last among data components. The heartbeat loop gains a
qdrant-liveness check with one bounded auto-restart, surfacing `degraded` state in
health and status output otherwise.

Server storage lives under the managed service directory (shared, multi-root), not
under any single project's data dir; per-root data is collections inside it. Local
mode keeps its per-project on-disk store unchanged as the zero-dependency default.

### Release pipeline and install UX

No new runtime dependency and no wheel-content change; optionally an extras marker
for documentation. CI gains a guard test (pin coverage for all six assets +
minor-match against the locked client) and an optional Linux smoke step that
provisions the real binary and checks its version. The publish workflow is
otherwise untouched.

New CLI group respecting the sync vocabulary and dry-run discipline:

- `server qdrant install [--upgrade] [--dry-run] [--binary PATH] [--json]` -
  reports created/unchanged/updated/skipped/failed; dry-run prints version, asset,
  URL, destination, and the digest it would verify, writing nothing.
- `server qdrant status [--json]` - provisioned versions, active binary and its
  resolution source, running-server liveness; bounded output.
- `server qdrant clean [--keep-current] [--yes]` - destructive, gated on --yes.
- `server start --qdrant` flips server mode; if the binary is absent it prints the
  exact install command and exits non-zero unless auto-provisioning was explicitly
  consented to. Operability state is computed in the service domain and mirrored
  across CLI, health payload, and a new MCP state tool.

### Security model

Committed SHA256 constants verified before extraction and before any execution;
the live release JSON digest is only consulted by a maintainer when authoring a
version bump. Checksum mismatch is a hard failure that deletes the partial
download. HTTPS-only, host-pinned fetches honoring proxy env vars. The
operator-binary env var bypasses fetching entirely for air-gapped setups. Loopback
binding always; the existing API-key plumbing remains for the remote-server escape
hatch. The kill-on-close Job Object doubles as a no-orphan guarantee.

### Implementation outline

Vault trail first: an ADR (topology = shared server + namespaced collections;
distribution = download-on-first-use; pin = code constant) and a plan precede code.
New runtime package with constants, asset resolution, provisioning, and supervision
modules (a direct analog of the CUDA pinning package plus the daemon spawn
helpers); edits to `config.py` (port/binary/server/storage knobs), the daemon spawn
helpers (qdrant spawn + Job Object), service lifespan (start/stop ordering, health
block), heartbeat (liveness), a new CLI command module, and lifecycle flags. The
store needs no logic change. Tests: real provisioning unit tests (asset resolution,
checksum mismatch, idempotent unchanged, dry-run writes nothing, pin guard) and a
real server-mode index+search round-trip integration test with shutdown-ordering
assertions, closed by an operator persona run. Sizing: about five new files and
seven edits - one cohesive feature.

### Sources

Retrieved 2026-06-12:

- https://github.com/qdrant/qdrant/releases (v1.18.2 asset names, sizes, embedded
  SHA256 digests) and issue 1733 (binaries shipped per release).
- https://qdrant.tech/documentation/installation/ and the qdrant Windows binary
  discussion (orgs/qdrant/discussions/2772).
- https://docs.pypi.org/project-management/storage-limits/ and PEP 759 (external
  wheel hosting).
- PyPI landscape: qdrant-client, qdrant-loader, qdrant-tools, mcp-server-qdrant -
  no maintained binary-bundling package.
- In-repo: the serving-runtime research; the store server-mode seam; the CUDA torch
  pinning package; the daemon process helpers; the locked qdrant-client version.
