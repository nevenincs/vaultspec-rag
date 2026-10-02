---
tags:
  - '#adr'
  - '#monitor-delivery'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:a69c78460587bd5a369e97aad2c65f2308510d2b13884a041338b97b0d15157f'
related:
  - "[[2026-10-02-monitor-delivery-reference]]"
  - "[[2026-10-02-monitor-delivery-research]]"
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
  - "[[2026-09-11-binary-release-bundles-adr]]"
  - "[[2026-09-30-release-standard-adr]]"
  - "[[2026-09-21-automatic-merge-gate-adr]]"
  - '[[2026-10-02-monitor-lifecycle-adr]]'
---

# `monitor-delivery` adr: `Ship the React monitor as a Bun executable in RAG bundles` | (**status:** `accepted`)

## Problem Statement

The React build does not deliver the local server bridge, and that bridge currently relies on checkout-local Python launch paths. RAG's release/acquisition contract omits the frontend. We need a runnable frontend whose assets and JavaScript runtime travel with it, and evidence that the shipped bytes work. Grounding: `2026-10-02-monitor-delivery-reference` and `2026-10-02-monitor-delivery-research`.

## Considerations

- Approved 2026-10-02: the user replied "sounds lovely" to the presented delivery ADR and six-Step implementation plan. This authorizes the recorded distribution/pin contract and implementation scope.
- React/Vite/npm and the shared devserver contract are accepted in `2026-09-30-monitor-tooling-adr`; local/tailnet transport, credentials and service ownership are accepted in `2026-09-30-monitor-browser-adr`.
- Concurrent `2026-10-02-monitor-lifecycle-adr` records explicit user authorization for backend-coupled monitor start/stop, backend-plus-one upward allocation and user-scratch discovery. Packaging integrates with that same owner; its source-only Vite requirement is the delivery extension being proposed here.
- Archive ownership and draft-first publication are accepted in `2026-09-11-binary-release-bundles-adr` and `2026-09-30-release-standard-adr`. Four targets are present in current code, as the new reference establishes.
- Toolchain provisioning and public binary launch must honor independently reviewed committed pins; a release's live checksum is insufficient as the only trust source.

## Considered options

- Embed Vite output and a small canonical bridge server in a Bun executable inside each existing RAG archive. Proposed: one installation/version contract and no frontend toolchain at launch.
- Compile the original React/HTML with Bun as a replacement frontend build. Rejected: creates migration and SCSS/plugin parity work unrelated to packaging.
- Publish an independent monitor archive/npm launcher. Deferred: useful for separate frontend release cadence, but requires a second acquisition/version-compatibility contract. The default proposal includes the executable in RAG bundles; user delivery preference can revise it before acceptance.
- Ship static assets or run Vite preview. Rejected: static assets omit the bridge and preview is development infrastructure rather than the delivered application server.

## Constraints

The delivered command is `vaultspec-rag-monitor` (`.exe` on Windows). Every supported RAG target archive contains this command together with the two existing commands. Current scope is Windows x64, Linux x64/ARM64 and macOS ARM64. It follows the same RAG release version, immutable producer SHA and artifact handoff. The root private package's `0.0.0` is never presented as the release version. There is one public target archive contract and one canonical frontend dependency lock, `package-lock.json`; Bun is a pinned compiler/embedded runtime, not a second package-manager migration.

The monitor embeds every local asset produced by the Vite release build, including fonts. It starts and serves the shell from any cwd without a checkout, external dist tree, JS runtime, Python or network acquisition. Startup/readiness and `--version` must not probe/start/bootstrap the backend. The backend-unavailable view remains useful when no RAG service or command is installed. Full monitoring requires the existing local service; service controls and persisted inventory use the canonical RAG owner and retain that owner's accelerator/bootstrap requirements. No offline-backend promise is introduced.

Use one shared bridge implementation across Vite dev/preview and the compiled server. Preserve bounded reads, timeouts, cancellation, exact operation admission, redaction, local service discovery, same-origin authority and the accepted local/tailnet client policy. Production retains the declared 0.0.0.0 host. Normal installed use is the canonical daemon's managed monitor: begin at the actual backend port plus one, retry upward without wrapping, publish the chosen assignment and couple shutdown to the daemon as monitor-lifecycle rules. The compiled command preserves the existing readiness line and parent-pipe EOF shutdown contract. A direct diagnostic launch may accept a validated explicit strict port; it neither starts the backend nor creates a second supervisor. Fixed manifest ports continue to govern source dev/preview only. Tailscale/proxy enrollment remains with its existing owner. No login or browser token is added.

In managed mode, reuse the absolute Python runtime supplied by the canonical daemon owner; it belongs to that owner's initialized environment and is not a system-Python prerequisite. For independent diagnostic use, resolve the shipped sibling RAG command relative to the executable, with an explicit absolute operator override and a verified installed-command option. Do not derive production cwd/PYTHONPATH from source imports or require uv/system Python. Subprocesses use fixed arguments, no shell, bounded output/time and cancellation. Expose persisted inventory through the canonical RAG CLI using `monitor_inventory.read_inventory` and its existing domain owners; command spelling is an implementation hypothesis. Missing/mismatched owners produce actionable unavailable results. Browser input cannot choose executables, modules or arbitrary arguments.

Restore npm dependencies from the committed lock and run the frontend gates. Build the Vite output once for a release source SHA/version/lock digest, then hand that exact output to each native Bun compilation job. Pin and verify the Bun archive and executable for each build host before extraction/execution; native compilation must not make implicit cross-target downloads. Disable ambient dotenv/bunfig loading in the compiled command. Generated asset maps and intermediate binaries remain outside Git. Final resources/signing/permissions finish before digests. Emit bundle manifest schema v2 with explicit component/runtime requirements and per-executable platform evidence; update its producers, validators and consumers together. The enclosing Linux bundle floor remains at least the current RAG 2.39 floor, regardless of the monitor's individual floor.

The draft completeness gate requires all target archives to contain the monitor, complete asset/version/provenance metadata, and successful native delivered-binary smoke evidence. The smoke launches finalized bytes in an isolated working directory, home and status directory with development commands unavailable and outbound networking disabled, checks readiness, all asset references, backend-unavailable behavior, occupied-port failure and bounded shutdown. A browser check renders the binary's HTTP output. Backend-control integration exercises real owners separately and cannot be replaced by shell smoke. No release/index/channel operation runs during these tests.

Publication order remains the accepted release standard. Public acquisition extends to every shipped monitor target and launches checksum-verified downloaded bytes after publication. A reviewed committed pin catalog binds release tag, source revision, target archive SHA256 and monitor executable SHA256; verify before extraction and immediately before launch, with HTTPS/redirect/host checks and explicit member extraction. Live SHA256SUMS and bundle hashes are additional consistency checks. A tag without reviewed pins is unverified and fails closed; generated pin proposals do not authorize themselves. The public launch probe follows the reviewed pin handoff, while native build proof still gates the draft. The exact catalog owner/path and review handoff must be made concrete within this commitment before rollout.

### Authorized reconciliation of accepted records

Approval covers these reconciliations. Apply each before its dependent implementation while preserving concurrent accepted lifecycle amendments.

- In `2026-09-11-binary-release-bundles-adr`, replace the first Constraints bullet with: "The public bundle unit is one versioned archive per supported RAG target: ZIP on Windows and TAR.GZ on Unix. It contains stable vaultspec-rag, vaultspec-search-mcp and vaultspec-rag-monitor executables, generated manifest.json, license and usage material. The manifest distinguishes the self-contained monitor frontend from the RAG accelerator/runtime bootstrap requirements." Replace the two-command/three-target Considerations sentence with: "Executable membership and supported targets follow the product declaration and release matrix; current packaging adds a monitor component with its own runtime requirements. Grounding: 2026-10-02-monitor-delivery-reference." Retain the remaining archive and publication commitments.
- In `2026-09-30-monitor-browser-adr`, replace the first Implementation sentence with: "Implement one server-side local bridge shared by Vite dev/preview and the packaged monitor server; it forwards bounded service operations and invokes portable canonical owner commands without exposing credentials." Replace the first two Consequences sentences with: "npm dev/preview owns development through the existing harness. Release delivery uses the compiled monitor server with embedded frontend assets, as governed by monitor-delivery; static assets alone remain insufficient."
- Append to `2026-10-02-monitor-lifecycle-adr` Constraints: "Installed releases use the bundled compiled monitor under the same daemon supervisor, allocation, discovery and shutdown contracts; source development may retain its Vite entry. Packaging supplies runtime resolution and does not create a second lifecycle owner."
- Append to `2026-09-30-monitor-tooling-adr` Constraints: "The npm lockfile and Vite build remain canonical. For release delivery, monitor-delivery adds Bun solely for native server compilation and embedded asset packaging; the compiled command does not require npm, Node, Vite or the shared development harness at launch."

## Implementation

We will add the monitor to the existing RAG bundle and reuse its archive/channel/release lifecycle. The existing monitor_process supervisor selects the packaged command for installed use and retains its current identity, rollback, allocation and cleanup authority. Share managed allocation/readiness/parent-pipe behavior between the source and compiled entry rather than duplicating it. The likely implementation separates the Vite plugin from the shared middleware, adds `src/monitor/server/standalone.ts`, generates static file imports over the exact Vite dist output, and compiles the server using a verified native Bun. A node:http server is a candidate because it can reuse the current middleware directly; the asset serving API is selected by the native build spike. The product model, manifest validation and channel generators consume the third stable command. Existing merge-gate admission governs build proof; no second PR owner or required check context is introduced.

## Rationale

The existing archive is the smallest boundary that carries the frontend server, its canonical owner command and shared version identity together. Retaining Vite keeps one tested React/Carbon compilation path. Separating shell launch proof, backend integration and public acquisition makes each guarantee observable without triggering an accelerator download to serve a page. The research favors this shape while leaving application-specific compilation to verification.

## Consequences

Users extract one RAG archive and canonical server start launches its bundled monitor; direct monitor launch also supports isolated diagnostics. Ordinary frontend startup is independent of development tooling. Builds acquire a pinned Bun compiler, the manifest evolves, and release proof gains native frontend checks on four targets. Public acquisition also needs an independently reviewed release-pin handoff. The backend remains a separate running service with its existing first-launch requirements. Reconsider this ruling if independent monitor releases, additional target platforms, remote multi-user service access or a bunx package become requirements. Acceptance establishes the contract; it does not claim that a binary has already been built or tested.
