---
tags:
  - '#adr'
  - '#qdrant-provisioning-trust'
date: '2026-10-05'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:3b514378f30bc445da5e8f877d8d5579902433e2a22031a95731108c6e8a7d85'
related:
  - "[[2026-10-05-qdrant-provisioning-trust-audit]]"
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
  - "[[2026-06-13-provisioning-setup-adr]]"
  - "[[2026-06-13-server-first-default-adr]]"
  - "[[2026-09-04-cuda-provisioning-adr]]"
  - "[[2026-06-12-qdrant-server-provisioning-research]]"
  - '[[2026-10-05-qdrant-provisioning-trust-research]]'
---

# `qdrant-provisioning-trust` adr: `automatic host provisioning and executable-anchored trust for the managed qdrant binary` | (**status:** `accepted`)

## Problem Statement

A host installation that has never provisioned the managed Qdrant server cannot complete a default `server start`: the binary is fetched only behind an explicit consent flag, while the model weights the same command needs are fetched without one. The path that does fetch and run the binary also falls short of the verify-before-execute contract it was built on. `2026-10-05-qdrant-provisioning-trust-audit` shows an implicit PATH lookup that runs a file from the working directory on Windows, a pre-execution check anchored to a digest stored beside the binary, restarts that re-execute without re-verifying, a recovery command that does nothing, and an install that is not atomic. This record decides the consent model for the binary on `server start`, where its trust is anchored, how it is resolved, and how its source is configured, and reconciles the two earlier provisioning records it changes.

## Considerations

- Model weights and the server binary are both fetch-and-go artifacts outside the Python environment (`2026-06-13-provisioning-setup-adr`); only the binary demands a consent flag on `server start`.

- A client installation never loads a model and cannot run the service (`2026-09-04-cuda-provisioning-adr`, D4); its role gate on `server start` currently sits after the binary check (`2026-10-05-qdrant-provisioning-trust-audit`, `start-does-not-provision`).

- The archive digest is a reviewed constant; the executable digest is not, so every check after extraction trusts the directory it is protecting (`pre-exec-self-attested`).

- The build toolchain already pins executable digests and checks them through one verifier; the qdrant path keeps a second, weaker comparison.

- An implicit PATH tier existed as a convenience when provisioning was opt-in. It runs an unpinned binary of unknown version and, on Windows, resolves from the working directory (`path-tier-cwd-exec`).

- The committed archive digests match the upstream release API for the pinned tag, so the pin table itself is sound and stays.

- GitHub Releases is the channel the earlier research selected (`2026-06-12-qdrant-server-provisioning-research`); its base URL and redirect hosts are code constants with no operator override, which blocks mirrors.

- GitHub Releases is the only first-party channel that yields a native executable on every supported platform; it is mutable and publishes no signatures or provenance, so a committed digest is the only integrity control (`2026-10-05-qdrant-provisioning-trust-research`).

- The Linux x64 gnu build is dynamically linked against a glibc floor that moves with upstream's build runner (2.38 at the pinned release). The musl build is static, already pinned, and is what the upstream package ships (`2026-10-05-qdrant-provisioning-trust-research`).

- Mirrors keep the upstream path suffix but may redirect to their own storage host, and the upstream platform has already moved its asset host once (`2026-10-05-qdrant-provisioning-trust-research`).

## Considered options

**D1 - consent for the binary on `server start`.**

- **O-1a (chosen) - a host start provisions the pinned binary when none resolves; invoking start is the consent, as it is for model weights.** An opt-out setting and flag restore fail-with-instructions.
- **O-1b - keep the explicit consent flag.** Rejected: the default command fails on every unprovisioned host and treats two like dependencies differently.
- **O-1c - provision inside the daemon.** Rejected: the daemon holds the machine lock and has no console; a first-use download belongs where progress and failure are visible.

**D2 - resolution tiers.**

- **O-2a (chosen) - operator binary setting, then the managed install; no PATH lookup.**
- **O-2b - keep PATH but accept only absolute hits outside the working directory.** Rejected: still an unpinned binary of unknown version, now with a platform-specific filter to maintain.
- **O-2c - keep PATH as is with a louder warning.** Rejected: a warning does not stop the execution the audit traced.

**D3 - trust anchor for execution.**

- **O-3a (chosen) - commit a per-asset executable digest beside the archive digest and check it after extraction and at every spawn.**
- **O-3b - keep the manifest digest and fail closed when it is absent.** Rejected: closes the skip but leaves the digest co-located with the artifact.
- **O-3c - re-verify the retained archive before each spawn.** Rejected: keeps a 30 MB archive per version and re-extracts on every start.

**D4 - source configuration.**

- **O-4a (chosen) - the release base URL and the allowed download hosts are settings with the official channel as default and prefixed environment overrides; digests stay code constants.**
- **O-4b - constants only.** Rejected: an operator behind a mirror has no supported route except hand-registering a binary.
- **O-4c - make digests overridable too.** Rejected: a digest that configuration can change is not a pin.

**D5 - Linux x64 asset.**

- **O-5a (chosen) - select the static musl build, as Linux arm64 already does.** No glibc dependency, one linkage model on Linux.
- **O-5b - keep the gnu build.** Rejected: a verified install then fails at spawn on any host below the moving glibc floor.
- **O-5c - probe glibc and choose.** Rejected: two paths and a platform probe to keep what one static build already covers.

**D6 - operator-supplied binary.** Added 2026-10-05 after execution showed that a registered binary is trusted on a manifest inside the directory it protects, so a writer to that directory can relabel a pinned download as operator-supplied.

- **O-6a (chosen) - one operator route: a setting naming an absolute file together with a setting declaring its SHA256, both from the process environment; the managed directory holds pinned downloads only.** An offline host installs the official archive from a local file through the same verified path.
- **O-6b - keep manifest registration with a label and a warning.** Rejected: the label is written by whoever wrote the manifest.
- **O-6c - keep the path setting with an optional digest.** Rejected: it leaves one spawn path that checks nothing.

**D7 - model weight revisions.**

- **O-7a (chosen) - every default model is fetched and loaded at a committed revision, as the sparse model already is; a revision setting accompanies each model setting.**
- **O-7b - keep the moving default branch for the dense and reranker models.** Rejected: an automatic download of unpinned content is the same gap the binary pin exists to close.

**D8 - binding verification to execution.**

- **O-8a (chosen) - the file that was hashed is the file that is executed: the verified path is passed as the executable itself, and the file is held against replacement between hashing and process creation wherever the platform offers a way.** A platform with no such mechanism is named as a stated residual, not left silent.
- **O-8b - verify then spawn by path.** Rejected as the end state: it leaves a replacement window and, on Windows, a command-line lookup that can pick a sibling file.

## Constraints

- Automatic provisioning runs only on a host installation. The installation role is decided before any network or filesystem effect. A client `server start` is refused before the binary check, and no client command - install, search, index, the MCP surface, warmup - downloads a model or a binary.

- The opt-out is a setting with a prefixed environment variable and a matching flag. With it off, an absent binary fails with the install command, as today. `--local-only` still skips the binary entirely.

- Verification order is fixed: archive digest before extraction, executable digest before the staged file replaces anything, executable digest again inside every spawn - first start, heartbeat restart, and recovery retry alike.

- Both digests come from reviewed code constants. A managed install whose executable digest is missing or mismatched never runs, and the remedy the failure names must actually repair it.

- An operator binary is explicit: a setting naming an absolute regular file, or a registration through the install verb. It carries no pin, is labelled as operator-supplied on every status surface, and is announced on the console at start, not only in the service log. A registered operator binary is verified against the digest recorded at registration.

- No lookup derives the binary from PATH or the working directory.

- An install is staged and replaced atomically; a failure at any stage leaves a previous install untouched. Provisioning is serialised across processes and the download has a whole-operation deadline.

- Source settings are read from the process environment and managed configuration only, never from a workspace file. HTTPS is mandatory for any configured source, and redirects stay inside the configured host set.

- Each fetch-and-go dependency has one provisioning implementation, reached by `install`, `server start`, `server warmup`, and the dependency's own verb, reporting in the shared sync vocabulary.

- This record overrides `2026-06-12-qdrant-server-provisioning-adr` on three points: the never-download-without-consent constraint, the PATH resolution tier, and the fixed host pin. It overrides the matching consent clause in `2026-06-13-provisioning-setup-adr`. Everything else in both records stands.

- A new install on Linux x64 uses the musl asset. The gnu pin stays in the table so an install made before this change keeps verifying: the manifest's asset name only selects which committed executable digest to compare, and an asset absent from the table never verifies.

- The base URL's own host is always permitted for the initial request; redirect targets must be in the configured host set. A digest mismatch is a hard failure that names the possibility of a replaced upstream asset; transient transport failures get a bounded retry.

- A platform with no upstream asset is reported as an unsupported outcome that names the operator binary route; it is never routed to another architecture's build.

- No process is created for the server binary without a digest check: a committed constant for a managed install, the operator-declared digest for an operator binary. An operator path without a declared digest is a start failure naming both settings.

- The manifest is never a source of trust. A manifest that claims an operator source is not honoured; such an install is reported as invalid with the two supported routes.

- An offline install takes a local copy of the official release archive and passes the same archive and executable digest checks as a download.

- Readiness and status surfaces report a managed install as usable only after hashing it.

- Default model revisions are committed constants, overridable by prefixed settings; a model named by the operator without a revision is fetched at the revision the operator's setting names or is reported as unpinned on every status surface.

- This overrides the earlier constraint in this record that a registered operator binary is verified against the digest recorded at registration.

## Implementation

We will make a host `server start` provision the pinned Qdrant binary by default, anchor its execution to committed executable digests, resolve it from an explicit operator setting or the managed install only, and read its source from settings.

- The start command decides the installation role first, then ensures models and the binary through the provisioning front door with visible progress, then spawns the daemon. The daemon resolves and verifies; it never downloads the binary.
- The pin table gains one executable digest per asset. The one native-binary verifier checks it after extraction and inside the supervisor's spawn. The manifest remains as a record of what was installed, not as a source of trust for a downloaded binary.
- Install-state classification hashes the executable, so the upgrade path replaces an install that fails its digest.
- Settings gain the auto-provision switch, the release base URL, and the allowed download hosts, each with a prefixed environment variable and the current official values as defaults. Hypothesis: the model hub endpoint and the CUDA wheel index take the same shape; if either collides with an existing canonical-configuration check, that source keeps its constant and the collision is recorded.
- Hypothesis: the start preflight ensures models through the same front door `install` uses, while the daemon's own model loading stays online-capable as a backstop for starts that bypass the command.

Outcome of the CUDA wheel index hypothesis: it fails. The index URL takes effect only by being written into a workspace file, is what the canonical-configuration check and the lockfile-derived torch version compare against, and is read by build tooling that cannot load settings. It stays a constant; an operator who needs a wheel mirror edits the index entry, which is classified as customised and never rewritten. The model hub endpoint hypothesis holds and is a setting published to the hub client at process start.

## Rationale

The consent flag protected against a surprise download, but the same command already downloads several gigabytes of model weights on first use, so the flag bought no real control and cost a failing default. Making start the consent, on hosts only, gives one behaviour for both dependencies and keeps the opt-out for operators who want it.

The trust decisions follow from one observation in `2026-10-05-qdrant-provisioning-trust-audit`: every check after extraction read its expected value from the directory under protection. Committing the executable digest removes that dependency at each point the audit found - the skipped check, the unverified restart, the gap between hashing and extracting, and the recovery that could not see a tampered file - with a pattern the build toolchain already uses.

Removing the PATH tier is the knockout for the working-directory execution: once provisioning is automatic there is no unprovisioned state for the convenience to serve, and the explicit operator setting covers every legitimate use of a system binary.

Configurable sources are safe only because digests are not configurable. A mirror can change where bytes come from, never which bytes run.

## Consequences

- A default `server start` on an unprovisioned host downloads about 30 MB without asking. Operators who relied on the refusal set the opt-out.

- An operator who relied on a `qdrant` found on PATH must name it through the operator binary setting or register it. This is a breaking change for that configuration and must be stated in the release notes and the installation guide.

- A version bump now re-derives two digests per asset instead of one.

- An existing managed install whose executable does not match the committed digest stops starting until it is reinstalled; the upgrade verb repairs it.

- Client installations are unaffected by design, and a client start no longer reaches any provisioning code.

- Reconsider if upstream begins publishing signed provenance for release binaries: signature verification would then be a stronger anchor than a transcribed digest.

- New Linux x64 installs run the musl build; its performance relative to gnu is unmeasured and is the condition to revisit if indexing or search regress on Linux.

- Because upstream assets are mutable, a replaced asset fails every new install until the pin is re-derived. That is the intended alarm.

- `server qdrant install --binary` is removed. An operator running a custom build sets the path and its digest; an air-gapped operator installs the official archive from a local file. Both are breaking changes for existing registered installs and must be stated in the release notes.

- Pinning the dense and reranker revisions makes a first start after upgrade fetch any file that changed between the cached revision and the pinned one.
