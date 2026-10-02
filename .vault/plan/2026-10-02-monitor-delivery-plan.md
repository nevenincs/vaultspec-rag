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
body_hash: 'sha256:6e54729016856e3963da5fedfd9cd8c1fa0dc71274ad00d0c166937f8a6acaaa'
---

# `monitor-delivery` plan

## Description

Draft for implementation. The user's 2026-10-02 request authorizes review and design; no implementation approval or accepted monitor-delivery ruling is recorded. This L1 plan preserves sequencing across sessions. The separate monitor-browser S03 tailnet-enrollment Step stays with its existing plan.

Decision coverage: proposed `2026-10-02-monitor-delivery-adr` governs delivery, portable owner launch, pins, manifest evolution and acquisition across all Steps. Accepted monitor-browser governs transport/credential/domain behavior in S01-S02; monitor-tooling governs npm/Vite and canonical harness parity in S01-S04. Concurrent monitor-lifecycle records explicit authorization for daemon-coupled monitor allocation/discovery/shutdown and supplies the shared supervisor seam in S01-S02. Its owning session must normalize the scaffolded accepted body before dependent execution. Binary-release-bundles governs archive/channel finalization in S03-S05; release-standard and automatic-merge-gate govern CI admission/publication order in S04-S05. Apply older-ADR amendments proposed by monitor-delivery only after acceptance, before dependent execution. This draft authorizes no remote publication, dispatch, default-branch change or external channel/Tailscale edit.

Default delivery is a third stable command in current RAG archives. The daemon uses that command in installed mode under the same supervisor/readiness/parent-pipe contracts; source dev/preview keep their established manifest ports. S01 selects reviewed exact Bun archive/executable pins for four hosts before using the toolchain. S05 makes the independent release-pin catalog and reviewed handoff concrete; downloaded public bytes cannot launch without it. Backend-control integration uses isolated canonical owners, separately from offline frontend startup.

## Steps

- [ ] `S01` - Make the bridge and existing lifecycle supervisor accept portable owner/runtime launch, and pin/verify native Bun provisioning; `src/monitor/server/local-service.ts and managed.ts, new vite-plugin.ts and standalone.ts, vite.config.ts, package.json/tsconfig.json, src/vaultspec_rag/monitor_process.py and monitor_inventory.py and cli, new tools/binaries/bun_toolchain.py, bridge/inventory/lifecycle tests`.
- [ ] `S02` - Embed the exact Vite output, compile versioned monitor binaries, integrate managed readiness/EOF/allocation and add the delivered-binary probe; `new tools/monitor build and smoke tooling, shared src/monitor/server managed and standalone runtime, package scripts/types/lock as needed, justfile, dev/monitor-browser.mjs, compiled and coupled-runtime tests`.
- [ ] `S03` - Add the monitor to every target archive, evolve the manifest to v2 and verify channel installation of all three commands; `tools/packaging/products.py, bundles.py, scoop.py, homebrew.py, generate.py, validate.py and tests, tools/binaries Windows resource/floor integration`.
- [ ] `S04` - Build the frontend once from the release SHA, hand it to native jobs and require smoke evidence before the draft publication handoff; `.github/workflows/binaries.yml, merge-gate.yml and publish.yml only where needed, dev/toolchain.py, justfile, dev/guards, tools/binaries/tests/test_release_workflow.py`.
- [ ] `S05` - Define reviewed release pins and extend public acquisition to native monitor launch on every shipped target with the shared probe; `.github/workflows/acquisition.yml, reviewed release-pin catalog and validation, tools/monitor acquisition integration, workflow/pin guards, catalog authority and handoff fixed before public launch`.
- [ ] `S06` - Document extraction, monitor launch and backend prerequisites, then review integrated delivery and its verification evidence; `docs/installation.md, docs/service-mode.md, RELEASING.md, monitor-delivery audit, authorized prior ADR amendments`.

## Parallelization

Execute sequentially in this worktree: S01 -> S02 -> S03 -> S04 -> S05 -> S06. One executor owns shared source, workflow, vault and commit mutations; no parallel agent assignments. Native CI target jobs may run concurrently after the common frontend artifact is proven and handed off.

## Verification

Before each implementation commit, run the configured lint, format and type gates covering its files plus meaningful affected tests, recording exit codes separately. Reuse npm checks, Python tooling, workflow lint and packaging checks. New negative guards require an uninterrupted intentional mutation/failure/restore/pass proof recorded beside the test or its evidence.

On Windows x64, Linux x64/ARM64 and macOS ARM64, verify version/producer identity, isolated launch with development commands unavailable, offline shell startup, all HTML/JS/CSS/font/dynamic asset references and MIME types, a browser page rendered from the compiled server, occupied-port failure, backend-unavailable semantics, cancellation and bounded shutdown. Node source imports or Vite rendering do not substitute for binary proof. Real lifecycle/inventory integration uses canonical owners and temporary status/storage roots; merely serving the shell must not initialize inference or trigger backend bootstrap.

Require one frontend build keyed by source/version/lock digest, four native results, finalization before hashing, exact three-command bundle contents, manifest/runtime/floor/provenance validation, checksum coverage and successful native smoke evidence before draft handoff. Failure branches leave the draft unpublished. Public acquisition verifies committed reviewed pins before extraction and immediately before execution, accepts exact regular-file members, probes downloaded monitor bytes on every target and cleans up its owned processes/paths without touching the operator's service or configuration.

Run owning vault/plan checks at durable checkpoints. Completion requires every Step closed and an integrated vaultspec-code-review of runtime, archive, channels, workflows and documentation; reuse applicable evidence and report uncompleted compiler/platform/backend validation explicitly.
