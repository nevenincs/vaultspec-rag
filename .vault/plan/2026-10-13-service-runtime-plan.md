---
tags:
  - '#plan'
  - '#service-runtime'
date: '2026-10-13'
tier: L1
related:
  - '[[2026-10-13-service-runtime-adr]]'
  - '[[2026-06-24-service-doctor-liveness-adr]]'
  - '[[2026-10-13-service-runtime-audit]]'
  - '[[2026-10-12-destructive-rebuild-lifecycle-adr]]'
modified: '2026-10-14'
body_schema: body-v2
body_hash: 'sha256:466235884a1d5979e0ff1c6c2a67e2260b7d5e504522b39f77909497e85d1c9f'
---

<!-- RETIRED: S05 -->

# `service-runtime` plan

Every install route starts the service with one command, and every refusal names one cause and one command.

## Description

Approved 2026-10-13. Basis: the user's "fix all", in reply to a lab report listing these defects and proposing this work, including the service-runtime decision.

Make every install route start the service with one command, and make every install, start, doctor and status message one cause and one command. `2026-10-13-service-runtime-adr` governs S02 and S03 (the managed runtime and the messaging rule). `2026-06-24-service-doctor-liveness-adr` governs S04. S06 is a routine correction within settled decisions. S05 (workspace MCP registration on install) was handed to another session at the user's assignment, with this lane's findings; its identifier is retired. The defects are recorded in `2026-10-13-service-runtime-audit`. Monitor provisioning (the audit's wheel-start finding) is owned by `2026-10-13-monitor-provisioning-plan` in another lane and is out of scope here; S07 verifies against whichever monitor state has landed.

## Steps

- [x] `S01` - record the lab audit, accept the service-runtime ADR, and reconcile the amended ADRs; `.vault/adr/2026-10-13-service-runtime-adr.md`.
- [x] `S02` - provision a managed service runtime and select it when the launching environment cannot serve; `src/vaultspec_rag/cli/_process.py`.
- [x] `S03` - collapse every install and start refusal to one cause and one command; `src/vaultspec_rag/operator_state/_provisioning.py`.
- [x] `S04` - make server doctor and status report a failed or absent service truthfully; `src/vaultspec_rag/cli/_service_doctor.py`.
- [x] `S06` - trim install and start help to user-facing options and rewrite the install docs around one command; `src/vaultspec_rag/cli/_install.py`.
- [ ] `S07` - verify every install route in the clean-machine GPU lab on Linux and Windows; `X:/project/vaultspec-rag-lab`.
- [x] `S08` - admit the first index of a new source as a full build, per the 2026-10-14 amendment; `src/vaultspec_rag/_job_admission.py`.

## Parallelization

S02 and S04 run in parallel in separate worktrees with disjoint write ownership. S03 follows S02 because both edit `src/vaultspec_rag/cli/_service_start.py`. S06 follows S03 so the docs describe final behaviour. S07 runs last. Files owned by the monitor-provisioning lane are never edited here: `src/vaultspec_rag/monitor_process.py`, `src/vaultspec_rag/_program_lookup.py`, `src/vaultspec_rag/qdrant_runtime/`, the monitor step in `src/vaultspec_rag/commands/_provision.py`, workflows, `tools/monitor`, `tools/packaging` and `tools/binaries`.

## Verification

- `uvx vaultspec-rag server start`, a pip venv install, and a uv tool install each reach a serving daemon in the lab on Linux and Windows. The monitor is excepted until its lane lands.
- Every refusal transcript in the lab shows one cause and at most one command.
- `server doctor` exits non-zero and reports not ready after a failed start and with no service running.
- The install integration tests pass.
- Lint, format, type checks and the covering tests pass for every Step; the final integrated review passes.
