---
tags:
  - '#plan'
  - '#status-messages'
date: '2026-09-23'
tier: L2
related:
  - '[[2026-09-23-status-messages-adr]]'
  - '[[2026-06-11-service-status-convergence-adr]]'
  - '[[2026-09-04-cuda-provisioning-adr]]'
  - '[[2026-06-10-preprocess-hooks-adr]]'
  - '[[2026-09-21-typesafe-classifier-adr]]'
  - '[[2026-06-24-service-doctor-liveness-adr]]'
modified: '2026-09-23'
body_schema: body-v2
body_hash: 'sha256:5a4fa5792828bd380fd6320d359da152ca24285953f8af58bd3e44fb2aa71d4e'
---

# `status-messages` plan

Replace fragmented, stringly-typed operator state with one typed state model and render it as plain-language status.

## Description

Approved 2026-09-23. Basis: the user authorised the plan in advance ("once you have
written the ADR the plan is yours and auto-approved") after asking for the ADR to be
written and verified by an independent fresh-context agent. The verifier returned
accept-with-changes. All 17 findings were applied to
`2026-09-23-status-messages-adr` and its research before acceptance.

Scope: implement `2026-09-23-status-messages-adr`.

- **P01** creates the torch-free state vocabulary and wire models.
- **P02** derives role, compute and hardware once, through the isolated
  daemon-interpreter probe, and repoints every consumer.
- **P03** makes the service author its health, degradation reasons and feature state
  (Typesafe, preprocess hooks, reranker, sparse, watcher, storage, models) on typed
  routes.
- **P04** types the client transport, extends `compose_discovery_status` into the only
  lifecycle composer, and types the MCP index-status tool.
- **P05** renders the plain-language overviews and closes with docs and a manual
  persona pass.

Every Step deletes the derivations it replaces in the same commit. No compatibility
aliases are kept, and tests are repointed at production paths.

Decision coverage:

- `2026-09-23-status-messages-adr` governs all Phases.
- `2026-06-11-service-status-convergence-adr` governs the service-domain ownership in
  P03 to P05.
- `2026-09-04-cuda-provisioning-adr` D4 (absent by design is a state) governs P02.
- `2026-06-10-preprocess-hooks-adr` governs the lenient hook predicate in P03.
- `2026-09-21-typesafe-classifier-adr` governs the Typesafe state in P03.
- `2026-06-24-service-doctor-liveness-adr` governs the doctor changes in P02 and P04.

Evidence is in `2026-09-23-status-messages-research`.

Out of scope, per the ADR:

- installer defaults and client-only channels;
- the MCP tool-mode launch extras;
- the `--local-only` override;
- a content-policy configuration surface;
- reporting MCP read-only mode.

## Steps

### Phase `P01` - typed state vocabulary

Create the torch-free operator state package that owns every new enum, its labels and remediation, and the typed wire models.

- [x] `P01.S01` - create the operator state package with InstallRole, HardwarePresence and ComputeCapability enums owning labels, remediation and start-blocking, plus a fresh-interpreter torch-free import test; `src/vaultspec_rag/operator_state/`.
- [x] `P01.S02` - add ServiceLifecycle with exit codes, HealthVerdict, DegradationReason, TypesafeState and PreprocessHookState enums with exhaustive label tests; `src/vaultspec_rag/operator_state/`.
- [x] `P01.S03` - add extra-forbid pydantic wire models for health, service state, installation, compute, hardware and feature sections; `src/vaultspec_rag/operator_state/`.

### Phase `P02` - install role, compute and hardware verdicts

Derive role, compute capability and hardware once, through the isolated daemon-interpreter probe, and repoint every consumer at those verdicts.

- [x] `P02.S09` - replace the probe exit-code prose contract with a typed ComputeCapability and InstallRole result, add the metadata-only probe mode, and repoint the tool-env repair consumer; `src/vaultspec_rag/cli/_process.py, src/vaultspec_rag/commands/_tool_torch.py`.
- [x] `P02.S04` - add the bounded cached torch-free hardware probe using nvidia-smi and the Apple Silicon platform check; `src/vaultspec_rag/operator_state/`.
- [x] `P02.S10` - retire TorchDiagnosis and the admission torch reasons in favour of ComputeCapability across torch_config, readiness, gpu errors and admission; `src/vaultspec_rag/torch_config/, src/vaultspec_rag/_readiness.py, src/vaultspec_rag/cli/_gpu_errors.py, src/vaultspec_rag/_gpu_admission.py`.
- [x] `P02.S15` - make server start preflight, the post-install warning and the doctor torch axis consume the probe verdict so doctor no longer imports torch in the CLI; `src/vaultspec_rag/cli/_service_start.py, src/vaultspec_rag/cli/_install.py, src/vaultspec_rag/cli/_service_doctor.py`.

### Phase `P03` - service-authored health and feature state

Make the service the only author of its health, degradation reasons, compute and feature state, served as typed models on the health and service-state routes.

- [x] `P03.S11` - emit typed HealthVerdict and DegradationReason codes from the service and drop the model-device cuda flag; `src/vaultspec_rag/server/_lifespan.py, src/vaultspec_rag/service.py`.
- [x] `P03.S05` - make the Typesafe status read pure and typed with PENDING on fingerprint change; `src/vaultspec_rag/search/_typesafe_transport.py`.
- [x] `P03.S12` - add the single lenient hooks-will-run predicate and repoint every derivation, including preprocess status; `src/vaultspec_rag/indexer/, src/vaultspec_rag/server/_routes_reindex.py, src/vaultspec_rag/cli/_preprocess.py`.
- [x] `P03.S16` - serve typed health and service-state models carrying role, compute, cached hardware, per-service and per-root features, deleting the index-status alias keys and unused models, and have preprocess status read the running service's mode; `src/vaultspec_rag/api.py, src/vaultspec_rag/server/_routes.py, src/vaultspec_rag/server/_models.py, src/vaultspec_rag/cli/_preprocess.py`.

### Phase `P04` - client lifecycle and typed transport

Parse the typed wire models in the service client, extend the canonical lifecycle composer, and delete the CLI and MCP re-derivations.

- [x] `P04.S06` - parse health and service-state responses into the typed models in the service client transport; `src/vaultspec_rag/serviceclient/`.
- [x] `P04.S13` - extend compose_discovery_status to produce ServiceLifecycle and delete the CLI state derivations and doctor liveness re-derivation; `src/vaultspec_rag/serviceclient/_status.py, src/vaultspec_rag/cli/_status_render.py, src/vaultspec_rag/cli/_service_doctor.py`.
- [x] `P04.S07` - return the typed service-state model from the MCP index-status tool and correct its docstring; `src/vaultspec_rag/mcp/_tools.py`.

### Phase `P05` - plain-language status rendering

Render the typed state as plain-language overviews on status, server status, doctor and the jobs view, and close the feature with docs and a manual persona pass.

- [x] `P05.S08` - rewrite project status as a plain-language overview of service, installation, compute, features and next action with local-only facts when stopped and an interpreter divergence note; `src/vaultspec_rag/cli/_status.py`.
- [x] `P05.S14` - rewrite server status and doctor output on the shared enums and labels, replacing not-reported rows with one stopped line; `src/vaultspec_rag/cli/_jobs_tui_status.py, src/vaultspec_rag/cli/_jobs_tui_constants.py, src/vaultspec_rag/cli/_jobs_tui_header.py, src/vaultspec_rag/cli/_jobs_tui_cells.py`.
- [x] `P05.S17` - repoint the jobs TUI health and lifecycle pills at the shared enums; `src/vaultspec_rag/cli/_jobs_tui_status.py, src/vaultspec_rag/cli/_jobs_tui_constants.py`.
- [x] `P05.S18` - update user docs and changelog notes for the new status output and breaking JSON fields, and run a manual persona pass on client, host and CPU-build environments; `README.md, docs/`.

## Parallelization

Phases run in order, and so do the Steps within a Phase. Every later Phase imports
the P01 vocabulary.

- **P02 and P03** may overlap only where they touch disjoint files. Both edit consumers
  of `ComputeCapability`, so run them serially in one working tree.
- **P04** depends on the P03 wire models.
- **P05** depends on P04.

Commits are serial on `fix/status-messages`.

## Verification

- `uv run --no-sync ruff check src`, `ruff format --check` and `ty check` pass on the
  touched files at each Step.
- The tests covering each touched branch pass, including error and fallback branches.
- A fresh-interpreter test proves importing the operator state package, the service
  client and the CLI status modules leaves `torch` out of `sys.modules`.
- Guard tests for the torch-free import and for enum exhaustiveness at render sites
  are shown to fail on a deliberate mutation, then pass once it is restored.
- Search by meaning plus grep finds these gone from `src/`:
  - the prose-equality probe classifiers;
  - `TorchDiagnosis`;
  - the CLI `_compute_state`;
  - the `/health` `cuda` model-device flag;
  - the alias keys `gpu_name` and `vram_*` in status payloads;
  - substring degradation matching.
- The derivation of "hooks will run" has exactly one implementation.
- Manual persona pass: on this host, `vaultspec-rag status` from the `+cpu` tool
  environment names a GPU host with a CPU-only torch build and shows its fix, and from
  the `+cu130` venv reports compute ready. The following are also checked:
  - a client-only environment reads as a client, not a failure;
  - a stopped service renders one plain line;
  - a repo with a preprocess config and a Typesafe key shows both features on
    `status` and `server status`.
- Phase-close reviews and the final integrated review are appended to the
  status-messages audit, with no open critical or high findings.
