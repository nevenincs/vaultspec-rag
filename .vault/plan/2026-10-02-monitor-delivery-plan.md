---
tags:
  - '#plan'
  - '#monitor-delivery'
date: '2026-10-02'
tier: L1
related:
  - '[[2026-10-02-monitor-delivery-adr]]'
  - '[[2026-09-30-monitor-browser-adr]]'
  - '[[2026-09-30-monitor-tooling-adr]]'
  - '[[2026-09-11-binary-release-bundles-adr]]'
  - '[[2026-09-30-release-standard-adr]]'
  - '[[2026-09-21-automatic-merge-gate-adr]]'
  - '[[2026-10-02-monitor-lifecycle-adr]]'
modified: '2026-10-02'
body_schema: body-v2
body_hash: 'sha256:19470c6db2d0fe8de370c789f09c7473d66c0d83faf154b9b2eab5aa351d5a5a'
---

# `monitor-delivery` plan

## Description

Approved 2026-10-02. Authorization: the user's 'sounds lovely' approves the presented delivery ADR and implementation plan. This L1 plan preserves sequencing across sessions. The separate monitor-browser S03 tailnet-enrollment Step stays with its existing plan.

Decision coverage: accepted `2026-10-02-monitor-delivery-adr` governs delivery, portable owner launch, pins, manifest evolution and acquisition across all Steps. Accepted monitor-browser governs transport/credential/domain behavior in S01-S02; monitor-tooling governs npm/Vite and canonical harness parity in S01-S04. Concurrent monitor-lifecycle records explicit authorization for daemon-coupled monitor allocation/discovery/shutdown and supplies the shared supervisor seam in S01-S02. Its owning session has normalized the accepted body; verify its in-flight runtime without mutation in S02, then merge its completed lifecycle commit in S09 before integrated completion. Binary-release-bundles governs archive/channel finalization in S03-S05; release-standard and automatic-merge-gate govern CI admission/publication order in S04-S05. Apply older-ADR amendments proposed by monitor-delivery only after acceptance, before dependent execution. Scope excludes remote publication, dispatch, default-branch changes and external channel/Tailscale edits.

Default delivery is a third stable command in current RAG archives. The daemon uses that command in installed mode under the same supervisor/readiness/parent-pipe contracts; source dev/preview keep their established manifest ports. S01 selects reviewed exact Bun archive/executable pins for four hosts before using the toolchain. S05 makes the independent release-pin catalog and reviewed handoff concrete; downloaded public bytes cannot launch without it. Backend-control integration uses isolated canonical owners, separately from offline frontend startup.

## Steps

- [x] `S07` - Commit reviewed Bun archive pins before any extraction; `tools/binaries/bun_pins.py and approval records`.
- [x] `S08` - Derive and commit executable pins from verified Bun archives before compiler execution; `tools/binaries/bun_pins.py`.
- [x] `S01` - Make the bridge accept portable owner launch and provision verified native Bun; `src/monitor/server/local-service.ts, new vite-plugin.ts, vite.config.ts, src/vaultspec_rag/monitor_inventory.py and cli, qdrant_runtime/_provision.py, tools/binaries/bun_toolchain.py and native.py, build_pyapp.py native-target caller, binary and bridge tests, authorized prior ADR reconciliation. The standalone entry and existing lifecycle owner are verified against real compiled bytes in S02 with the stable in-flight lifecycle owner; its completed commit is merged in S09`.
- [x] `S02` - Embed the exact Vite output, compile versioned monitor binaries, preserve managed readiness/EOF/allocation and add the delivered-binary probe; `tools/monitor build/frontend/smoke tooling and tests, src/monitor/server/standalone.ts, dev/monitor-browser.mjs, shared native pre-execution verifier and product Windows metadata owner, product monitor declaration, justfile recipes. Verify Windows finalized bytes and canonical owner interoperability locally. The lifecycle owner merge belongs to S09, and additional native platform proof belongs to S04 and the integrated S06 review`.
- [x] `S03` - Add the monitor to every target archive, evolve the manifest to v2 and verify channel installation of all three commands; `tools/packaging/products.py, bundles.py, scoop.py, homebrew.py, generate.py, validate.py and tests, tools/binaries Windows resource/floor integration`.
- [x] `S04` - Build the frontend once from the release SHA, hand it to native jobs and require smoke evidence before the draft publication handoff; `binaries.yml common frontend/native/draft handoff, tools/monitor release admission and stronger shared probes/reference closure/common frontend hash, shared bundle evidence consumers, installed browser selector and existing source harness caller, justfile and generated output ignore, workflow/frontend/wheel/archive guards. Native CI executions remain required evidence for S06. No remote dispatch or publication authorized`.
- [ ] `S05` - Define reviewed release pins and extend public acquisition to native monitor launch on every shipped target with the shared probe; `.github/workflows/acquisition.yml, reviewed release-pin catalog and validation, tools/monitor acquisition integration, workflow/pin guards, catalog authority and handoff fixed before public launch`.
- [ ] `S09` - Merge the completed canonical lifecycle commit and verify combined delivery behavior; `feature/monitor into feature/monitor-delivery, src/vaultspec_rag/monitor_process.py and lifecycle integration tests, accepted monitor-lifecycle reconciliation and related links. Runtime interoperability is already proven against its stable in-flight owner source, but this Step remains open until that owner commits and combined code is reviewed`.
- [ ] `S06` - Document extraction, monitor launch and backend prerequisites, then review integrated delivery and its verification evidence; `docs/installation.md, docs/service-mode.md, RELEASING.md, monitor-delivery audit, authorized prior ADR amendments`.

## Parallelization

Execute sequentially in the isolated feature/monitor-delivery worktree. Commit archive pins, then derive and commit executable pins before S01 -> S02 -> S03 -> S04 -> S05 -> S09 -> S06. This preparatory split satisfies the committed-pin extraction and execution boundary. One executor owns shared source, workflow, vault and commit mutations; no parallel agent assignments. Native CI target jobs may run concurrently after the common frontend artifact is proven and handed off.

## Verification

Before each implementation commit, run the configured lint, format and type gates covering its files plus meaningful affected tests, recording exit codes separately. Reuse npm checks, Python tooling, workflow lint and packaging checks. New negative guards require an uninterrupted intentional mutation/failure/restore/pass proof recorded beside the test or its evidence.

On Windows x64, Linux x64/ARM64 and macOS ARM64, verify version/producer identity, isolated launch with development commands unavailable, offline shell startup, all HTML/JS/CSS/font/dynamic asset references and MIME types, a browser page rendered from the compiled server, occupied-port failure, backend-unavailable semantics, cancellation and bounded shutdown. Node source imports or Vite rendering do not substitute for binary proof. Real lifecycle/inventory integration uses canonical owners and temporary status/storage roots; merely serving the shell must not initialize inference or trigger backend bootstrap.

Require one frontend build keyed by source/version/lock digest, four native results, finalization before hashing, exact three-command bundle contents, manifest/runtime/floor/provenance validation, checksum coverage and successful native smoke evidence before draft handoff. Failure branches leave the draft unpublished. Public acquisition verifies committed reviewed pins before extraction and immediately before execution, accepts exact regular-file members, probes downloaded monitor bytes on every target and cleans up its owned processes/paths without touching the operator's service or configuration.

Run owning vault/plan checks at durable checkpoints. Completion requires every Step closed and an integrated vaultspec-code-review of runtime, archive, channels, workflows and documentation; reuse applicable evidence and report uncompleted compiler/platform/backend validation explicitly.
