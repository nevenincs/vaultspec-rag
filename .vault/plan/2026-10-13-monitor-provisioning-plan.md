---
tags:
  - '#plan'
  - '#monitor-provisioning'
date: '2026-10-13'
tier: L1
related:
  - '[[2026-10-13-monitor-provisioning-adr]]'
  - '[[2026-10-02-monitor-lifecycle-adr]]'
  - '[[2026-10-02-monitor-delivery-adr]]'
  - '[[2026-09-11-binary-release-bundles-adr]]'
  - '[[2026-10-05-qdrant-provisioning-trust-adr]]'
  - '[[2026-10-09-automatic-merge-gate-autonomous-release-adr]]'
modified: '2026-10-13'
body_schema: body-v2
body_hash: 'sha256:8ae10116a8fd6f075fad2d240cacd3a10ca11e76de1b0b1cb92b67252c2b2759'
---

# `monitor-provisioning` plan

Make wheel installations provision, verify and launch the compiled monitor with no user action.

## Description

Approved 2026-10-13. Basis: after reviewing the fully automatic revision of the monitor-provisioning decision and this plan's scope, the user replied "good plan and execute".

PyPI installations cannot start the service because managed start requires the compiled monitor, which only binary bundles ship. Accepted `2026-10-13-monitor-provisioning-adr` governs every Step: release-generated pins in the wheel, a per-target monitor-only archive, automatic provisioning on host `server start` and install, launcher resolution without PATH, and no user-facing setup step or instruction anywhere. Evidence is `2026-10-13-monitor-provisioning-reference`. `2026-10-05-qdrant-provisioning-trust-adr` supplies the provisioning pattern reused in S01, S03 and S04. `2026-10-02-monitor-lifecycle-adr` keeps lifecycle, allocation and shutdown unchanged in S03. `2026-09-11-binary-release-bundles-adr`, `2026-10-02-monitor-delivery-adr` and `2026-10-09-automatic-merge-gate-autonomous-release-adr` govern release order, assets and admission in S05. All three were reconciled when the decision was accepted. No other costly decision is involved.

Ownership boundary: peer session main-bf, on branch fix/install-ux, owns the `server doctor` verdict and exit code, start refusal messaging, install output, install documentation sections and a managed service runtime. This plan adds only a monitor entry on the readiness installed-dependencies axis, in the existing entry shape, and edits only the monitor lines of `docs/installation.md`. The daemon's interpreter may differ from the CLI's, so resolution must not assume they are the same. Work happens in the `monitor-provisioning` worktree on `feat/monitor-provisioning`.

## Steps

- [x] `S01` - Lift the native-binary install primitives both binaries need into one shared owner and repoint Qdrant at it; `src/vaultspec_rag/qdrant_runtime/ managed-install, spawn-trust and provision seams, the new shared owner module, and their tests`.
- [ ] `S02` - Define the generated monitor pin module, its loader and its generator; `src/vaultspec_rag pin loader, tools/monitor pin generator, pyproject.toml hatch artifacts inclusion, .gitignore, and tests`.
- [ ] `S03` - Provision, resolve and verify the monitor at runtime with the PATH tier removed; `new monitor runtime module, src/vaultspec_rag/monitor_process.py, src/vaultspec_rag/_program_lookup.py callers, src/vaultspec_rag/config/_types.py, _registry.py and _schema.py, and tests`.
- [ ] `S04` - Run the monitor step in server start and install provisioning and report it on the readiness dependency axis; `src/vaultspec_rag/commands/_provision.py, src/vaultspec_rag/cli/_render.py, src/vaultspec_rag/_readiness.py monitor entry only, and tests`.
- [ ] `S05` - Compile the monitor before the wheel, publish monitor-only archives and check bundle pins against the wheel; `.github/workflows/publish.yml, binaries.yml and acquisition.yml, tools/monitor/build.py and release.py, tools/packaging/bundles.py and validate.py, justfile release recipes, and tests`.
- [ ] `S06` - Make development monitor setup automatic and drop manual monitor setup from the docs; `justfile build-monitor recipes, tools/monitor/build.py test mode, .github/workflows/merge-gate.yml test jobs, docs/service-mode.md, docs/configuration.md, docs/installation.md monitor lines, dev/generate_cli_reference.py and docs/cli.md`.
- [ ] `S07` - Review the integrated provisioning, release and documentation changes; `monitor-provisioning audit`.

## Parallelization

Sequential, one executor. S01 precedes S03, which depends on the shared owner. S02 precedes S03 and S05, which consume the pin contract. S04 follows S03. S05 and S06 may follow S04 in either order. S07 runs last over the stable set.

## Verification

Before each commit, run ruff check and format over the package and tools, the type-checker over changed files, and the tests covering the touched branches, recording each exit code separately. After the S01 lift, run the Qdrant provisioning, download-fault, install-recovery and spawn-trust suites. Every new refusal guard (digest mismatch, unpinned build, missing pin for the target, override without digest, PATH not searched) gets a recorded break-fail-restore-pass proof.

The plan succeeds when, all with no user step: a release-built wheel installed into a fresh environment provisions the monitor on first host `server start`, verifies it before extraction, install and spawn, and starts offline on later runs; a mismatched or tampered download fails the start with a message that gives no setup instruction; an upgrade fetches the new version and retires the old one; and a bundle install uses its sibling monitor only when it matches the wheel's pin. A development build prepared by the repository recipes starts with no exported variable. The release workflows compile monitors before the wheel, publish monitor-only archives in `SHA256SUMS` with attestations, and fail bundle validation on any pin mismatch, which workflow lint and the packaging tests confirm. Completion requires every Step closed and an integrated vaultspec-code-review passing.
