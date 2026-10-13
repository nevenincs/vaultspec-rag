---
tags:
  - '#adr'
  - '#monitor-provisioning'
date: '2026-10-13'
modified: '2026-10-13'
body_schema: 'body-v2'
body_hash: 'sha256:f7f7b30388f48024f8acc02fdcb65852a8f913e4ca436055086fc27b06dc3730'
related:
  - "[[2026-10-13-monitor-provisioning-reference]]"
  - "[[2026-10-02-monitor-delivery-adr]]"
  - "[[2026-10-02-monitor-lifecycle-adr]]"
  - "[[2026-09-11-binary-release-bundles-adr]]"
  - "[[2026-10-09-automatic-merge-gate-autonomous-release-adr]]"
  - "[[2026-10-05-qdrant-provisioning-trust-adr]]"
---

# `monitor-provisioning` adr: `Provision the compiled monitor on server start from pins carried in the wheel` | (**status:** `proposed`)

## Problem Statement

A host installed from PyPI, as a standalone uv tool or a project dependency, cannot start the service. Managed startup requires the compiled `vaultspec-rag-monitor` executable and fails the coupled start without it, while the only artifact that ships it is the per-target binary bundle; the wheel is pure Python. `2026-10-02-monitor-lifecycle-adr` assigns acquisition to delivery, and `2026-10-02-monitor-delivery-adr` delivers only through bundles, so the wheel routes documented in the installation guide fall between the two records. This record decides how a wheel installation obtains and trusts the monitor, and reconciles the release-order and resolution wording it changes. Evidence: `2026-10-13-monitor-provisioning-reference`.

## Considerations

- The monitor is mandatory for a managed start and must stay so; a service without its monitor is not the delivered product (`2026-10-02-monitor-lifecycle-adr`).
- Qdrant already solves the same problem for a native binary outside the Python environment: automatic provisioning on `server start`, a managed directory, archive and executable digests, verification before extraction and before every spawn, and no PATH tier (`2026-10-05-qdrant-provisioning-trust-adr`). Its transport and verification primitives are generic (`2026-10-13-monitor-provisioning-reference`, Reusable provisioning primitives).
- The monitor is a same-repository release product, so no human can review its digests before the wheel ships; release-product trust is attestation-based (`2026-10-09-automatic-merge-gate-autonomous-release-adr`).
- The only public monitor bytes today sit inside the bundle, and the bundle embeds the wheel, so a wheel cannot carry the bundle's digest.
- The monitor compile reads no wheel bytes; its ordering behind the wheel is workflow topology only (`2026-10-13-monitor-provisioning-reference`, Release pipeline order).
- The executable is roughly 90 MB per target.
- The user chose provisioning on start over platform wheels and an optional monitor, and chose wheel-carried pins over runtime attestation verification (2026-10-13).

## Considered options

- Provision on `server start`, verified against monitor digests generated into the wheel by the release pipeline, downloading a monitor-only archive per target. Chosen: the trust anchor is the artifact already executing, no runtime verification dependency or network trust service is needed, and the download carries only the monitor.
- Provision on `server start`, verifying the bundle archive's Sigstore attestation at runtime. Rejected: adds a runtime Sigstore dependency (the `gh` CLI cannot be assumed), requires a trust-service round trip, and downloads the whole bundle to obtain one executable.
- Ship the monitor inside per-target platform wheels. Rejected: ends the pure-Python wheel, multiplies wheel builds by target, and puts each wheel near the package index's per-file limit.
- Start without the monitor when it is absent. Rejected: reverses the fail-closed coupled start and leaves wheel installs permanently without the delivered frontend.

## Constraints

Fully automatic. Obtaining, verifying, installing, upgrading and cleaning up the monitor requires nothing from the user: no command, flag, prompt, consent, environment variable, PATH entry or documentation step, exactly as for the models and the Qdrant binary. The installation guide's routes stay as they are and gain no monitor step. No message ever tells a user to install, download, configure or point at the monitor; a failure states what went wrong (for example, no network on the first start of a release) and that the next start retries. An upgrade provisions the new release's monitor on its first start and retires superseded versions it owns. Every environment of the same release on the host, including a uv ephemeral cache environment, shares one user-level managed install.

Version coupling. The wheel provisions only the monitor built from the same release source and version. There is no cross-version fallback and no "latest" lookup.

Release order. For a release, the frontend is built once and the native monitor is compiled and finalized for every shipped target before the wheel is built. The release pipeline packs each finalized monitor into a monitor-only archive per target and generates a pin module recording, per target, the archive SHA256 and the executable SHA256. The wheel and sdist carry that module. The bundle build then consumes that exact wheel and those exact monitor bytes; bundle validation fails if the bundled monitor's digest differs from the wheel's pin for that target. The per-target monitor archives are public release assets alongside the bundles, appear in `SHA256SUMS`, and carry the same attestation as the bundles. Draft-first publication and its admission gates are otherwise unchanged.

Trust. The generated pin module is trusted because it ships inside the artifact that performs the verification; anyone able to alter it can alter the verifier. It is never read from live release metadata, never fetched, and never configurable. Live checksums and attestations remain consistency checks. A source or development build carries no release pins; the repository's own development setup builds the monitor and records its digest for that build automatically, so a developer also configures nothing by hand. That development pin is never accepted by a release-built wheel.

Provisioning. Host `server start` provisions the monitor in the same step that provisions models and the Qdrant binary, reported through the same provisioning outcome vocabulary, after the client-role gate and before model warming. It downloads over HTTPS with the shared host-pinned, bounded downloader, verifies the archive digest before extraction, extracts the single expected member by basename, verifies the executable digest before installing it atomically into a versioned managed directory beside the managed Qdrant directory, and re-verifies it immediately before every spawn. A present, verified install performs no network access. A failed download or mismatch deletes the partial artifact and fails the coupled start. Client installations provision no monitor.

Resolution. The launcher resolves, in order: the monitor beside the running installation's programs when its digest matches the wheel's pin for this target (bundle installs); the managed install for the running version, provisioned automatically when absent. The PATH tier is removed; any installation that used it is served by the managed install with no action. An optional operator override, which requires an absolute path and its SHA256 as a pair under the same rules as the Qdrant operator pair, exists for operators running their own build; it is never required, never suggested by a message and never part of setup. Every resolved executable is verified against its expected digest before spawn.

Source of bytes. The download location follows the Qdrant pattern: a shipped default release URL with a pinned host, overridable to a mirror by an operator setting; which bytes may run is decided only by the pin module.

Scope. This record does not change monitor lifecycle, allocation, readiness, parent-pipe shutdown, access capability or bridge behaviour, and does not change release-product admission or the bundle contents beyond the consistency check above. Toolchain pins stay reviewed committed constants.

### Proposed reconciliation of accepted records

Applied only once this record is accepted.

- `2026-10-02-monitor-lifecycle-adr`, Constraints: replace "Resolve an explicit absolute `VAULTSPEC_RAG_MONITOR_BINARY` override, otherwise the installed command on PATH." with "Resolve the executable as `2026-10-13-monitor-provisioning-adr` orders it: the installation's own pinned sibling, then the automatically provisioned managed install, with an optional paired operator override; each is digest-verified before spawn and PATH is not searched." Replace "Package installation and verified binary acquisition belong to delivery; this launcher performs no download or provisioning." with "The launcher performs no download; host `server start` provisioning acquires and verifies the executable before the launcher runs, under `2026-10-13-monitor-provisioning-adr`."
- `2026-09-11-binary-release-bundles-adr`, Constraints: append to the version-checked-wheel bullet: "The native monitor compile precedes the wheel build so the wheel can carry its generated digests; the bundle then consumes that wheel and those monitor bytes and must match the wheel's pins, under `2026-10-13-monitor-provisioning-adr`." Append to the raw-target-names bullet: "A per-target monitor-only archive is also published as a release asset for wheel-installation provisioning; it is not a channel install unit."
- `2026-10-02-monitor-delivery-adr`, append under Constraints: "Wheel installations obtain the same finalized monitor bytes through `server start` provisioning from a per-target monitor-only release archive, verified against digests the release pipeline generates into the wheel, under `2026-10-13-monitor-provisioning-adr`."
- Rule `pinned-binaries-verify-before-execute` (user-owned policy source): replace "Take the digest from a reviewed code constant, never from live release metadata." with "Take the digest from a reviewed code constant, or for a same-release product from a pin module the release pipeline generates into the artifact that verifies it; never from live release metadata."

## Implementation

We will add a monitor provisioning step to host `server start` and make the release pipeline compile the monitor before the wheel. Implementation hypotheses that may change within the constraints:

- Reuse `download_https`, `file_sha256`, `extract_verified_archive` and `verify_native_binary` from `src/vaultspec_rag/qdrant_runtime/`; any part of the managed-install state machine that both binaries need is lifted into one shared owner rather than copied.
- The pin module is a generated, git-ignored Python module inside the package, absent from source checkouts; a build-backend hook or a pipeline step writes it before `uv build`.
- The monitor compile and monitor-only archive move from `binaries.yml` into a stage that runs before the wheel build, and `binaries.yml` consumes those artifacts instead of compiling them again.
- `VAULTSPEC_RAG_MONITOR_BINARY_SHA256` pairs with the existing path override as an operator knob only.
- The repository's development setup recipes, which already build the monitor (`just build-monitor`, `just build-monitor-test`), write the development pin and the managed install themselves, so tests and local service starts need no exported variable.

## Rationale

The wheel is the code that will run the check, so a digest generated into it carries exactly the wheel's own trust and needs no second trust service at runtime; a runtime attestation verifier would add a dependency and a network round trip to reach the same identity. The Qdrant path already embodies the verify-before-extract, verify-before-spawn, managed-directory and no-PATH contracts this product needs, so reusing it keeps one implementation. Moving only the monitor compile ahead of the wheel is possible because the compile never reads the wheel (`2026-10-13-monitor-provisioning-reference`).

## Consequences

PyPI installations start the service with its monitor after one download per release, and offline after that. Bundle installations keep their bundled monitor, now verified against the embedded wheel's pins. The release pipeline gains a stage and a public asset per target, and releases grow by about 90 MB per target. Users never see or perform a monitor setup step on any installation route; the only visible trace is the monitor line in the existing provisioning summary. Removing the PATH tier needs no migration because the managed install covers every case it served. Reconsider if the monitor gains an independent release cadence, if the generated pin cannot be produced before the wheel, or if a runtime attestation verifier becomes a dependency for other reasons.
