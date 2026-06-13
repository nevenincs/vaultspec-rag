---
tags:
  - '#plan'
  - '#server-first-default'
date: '2026-06-13'
tier: L3
related:
  - '[[2026-06-13-server-first-default-adr]]'
  - '[[2026-06-13-provisioning-setup-adr]]'
---

# `server-first-default` plan

Flip the RAG default to the supervised Qdrant server backend, consolidate dependency provisioning behind one opt-out setup front door, add a bounded readiness verb, and reframe the docs so server-first is standard and local-only is the explicit minimal alternative.

## Wave `W01` - runtime default flip

Make the resident service default to the supervised Qdrant server backend, with --local-only (and the existing server-mode env knob) as the first-class explicit opt-out, and a loud, actionable failure when the server cannot start. Per-root namespacing and backend-aware store locking already exist and are not re-implemented here. This Wave is the foundation: W02 setup, W03 readiness, and W04 documentation all describe and provision the default this Wave establishes, so it must land first.

### Phase `W01.P01` - config default and selection

Flip the runtime backend default to server mode in config and introduce a single local-only selection knob honored across config resolution.

- [x] `W01.P01.S01` - flip the qdrant_server default from False to True in the RAG defaults so server mode is the assumed backend; `src/vaultspec_rag/config.py`.
- [x] `W01.P01.S02` - add the LOCAL_ONLY env var member and its \_ENV_OVERRIDE_MAP entry so a single knob selects the local backend across config resolution; `src/vaultspec_rag/config.py`.
- [x] `W01.P01.S03` - add a local_only RAG default and resolve effective server mode as qdrant_server and not local_only so local-only deterministically wins; `src/vaultspec_rag/config.py`.
- [x] `W01.P01.S04` - add unit tests asserting the server-mode default and the local-only override precedence across env and default resolution; `src/vaultspec_rag/tests/test_config.py`.

### Phase `W01.P02` - service startup and failure contract

Make the resident service start server mode by default, select the local store when local-only is chosen, and fail loudly and actionably when the server cannot start.

- [x] `W01.P02.S05` - make service_lifespan select server mode by default and use the local store only when local-only is set, reading effective server mode from config; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `W01.P02.S06` - convert the qdrant child startup failure into a loud, actionable startup abort that names the install command and the --local-only escape hatch; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `W01.P02.S07` - surface the loud server-start failure remediation in the start-supervised entry point error message preserving verify-before-execute; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [x] `W01.P02.S08` - add integration tests for the server-first default startup path and the local-only opt-out startup path; `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`.

### Phase `W01.P03` - CLI start surface and tests

Expose --local-only on the start surface, translate it to the daemon env, and cover the default flip plus opt-out with tests.

- [x] `W01.P03.S09` - add a --local-only flag to server start that selects the local backend and reframe the existing --qdrant flag as the redundant explicit-server opt-in; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `W01.P03.S10` - translate the --local-only start flag into the VAULTSPEC_RAG_LOCAL_ONLY daemon env, leaving operator-set env untouched when unset; `src/vaultspec_rag/cli/_process.py`.
- [x] `W01.P03.S11` - default the qdrant-binary pre-start guard to run by default and skip it under --local-only so a default start fails fast on a missing binary; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `W01.P03.S12` - add CLI tests covering --local-only env translation, the default server-mode start, and the missing-binary loud-failure path; `src/vaultspec_rag/tests/test_cli.py`.

## Wave `W02` - unified setup front door

Give install/setup one opt-out provisioning front door that configures torch (reporting 'configured, sync pending'), ensures models, and provisions the Qdrant binary by default; --local-only skips the binary and selects the local runtime; finer per-dependency skips exist; every step reports through the shared sync vocabulary, is idempotent, and supports --dry-run. It reuses the existing torch configurator, model warmup path, and qdrant_runtime provisioner as backends. Depends on W01 because the runtime default it provisions for is the one W01 establishes.

### Phase `W02.P04` - provisioning front door orchestration

Add an opt-out provisioning orchestrator over the existing torch, model, and qdrant backends that reports through the shared sync vocabulary, is idempotent, and supports dry-run.

- [x] `W02.P04.S13` - create a provisioning front-door module that orchestrates torch, model, and qdrant provisioning and returns a heterogeneous per-dependency result; `src/vaultspec_rag/commands/_provision.py`.
- [x] `W02.P04.S14` - wrap the torch configurator step in the front door so it reports configured-with-sync-pending through the shared sync vocabulary; `src/vaultspec_rag/commands/_provision.py`.
- [x] `W02.P04.S15` - add a model-ensure provisioning step that reuses the warmup snapshot-download path and reports cached versus downloaded idempotently; `src/vaultspec_rag/commands/_models.py`.
- [x] `W02.P04.S16` - add a qdrant-binary provisioning step that delegates to the existing provisioner and maps its action onto the shared sync vocabulary; `src/vaultspec_rag/commands/_provision.py`.
- [x] `W02.P04.S17` - export the front-door orchestrator from the commands package public surface; `src/vaultspec_rag/commands/__init__.py`.

### Phase `W02.P05` - setup CLI surface and opt-outs

Wire the provisioning front door into the install/setup CLI command with --local-only and finer per-dependency skip flags, honoring local-only at the runtime layer too.

- [x] `W02.P05.S18` - call the provisioning front door by default from install_run and thread its result into the install report; `src/vaultspec_rag/commands/_install.py`.
- [x] `W02.P05.S19` - add --local-only to the install command so it skips the qdrant binary and selects the local runtime default; `src/vaultspec_rag/cli/_install.py`.
- [x] `W02.P05.S20` - add per-dependency skip flags for torch, models, and qdrant to the install command for finer opt-out than --local-only; `src/vaultspec_rag/cli/_install.py`.
- [x] `W02.P05.S21` - honor --local-only in install_run by writing the local-only runtime selection so the setup choice persists to runtime; `src/vaultspec_rag/commands/_install.py`.

### Phase `W02.P06` - provisioning report and tests

Extend the install report to carry heterogeneous per-dependency outcomes honestly and cover idempotency, dry-run, and local-only skipping with tests.

- [x] `W02.P06.S22` - extend InstallReport with per-dependency provisioning outcomes and render them honestly in the human and JSON report; `src/vaultspec_rag/commands/_models.py`.
- [x] `W02.P06.S23` - render the heterogeneous provisioning outcomes in the install report renderer including the torch sync-pending wording; `src/vaultspec_rag/cli/_render.py`.
- [x] `W02.P06.S24` - add tests for front-door idempotency, dry-run preview, and the local-only binary skip on the provisioning orchestrator; `src/vaultspec_rag/tests/test_provision.py`.
- [x] `W02.P06.S25` - add an integration test for the default install provisioning path reporting heterogeneous per-dependency outcomes; `src/vaultspec_rag/tests/integration/test_install.py`.

## Wave `W03` - readiness verb

Add a bounded, read-only readiness/doctor command in the service domain that reports per-dependency provisioned and usable state - torch CUDA availability, model presence, and the Qdrant binary resolution source plus supervised-server liveness - so a user learns what is missing before a runtime failure. The CLI and MCP adapt to this shared service-domain behavior rather than owning it. Depends on W02 because it reports the state that the setup front door provisions.

### Phase `W03.P07` - service-domain readiness reporter

Build the bounded, read-only readiness model in the service domain that aggregates per-dependency provisioned and usable state.

- [x] `W03.P07.S26` - add a get_readiness facade function that aggregates the bounded per-dependency readiness snapshot in the service domain; `src/vaultspec_rag/api.py`.
- [x] `W03.P07.S27` - report torch CUDA availability as a readiness dimension without forcing model load; `src/vaultspec_rag/api.py`.
- [x] `W03.P07.S28` - report model presence by checking the HuggingFace cache for the configured dense, sparse, and reranker repos; `src/vaultspec_rag/api.py`.
- [x] `W03.P07.S29` - report the qdrant binary resolution source and supervised-server liveness by reading the qdrant runtime state; `src/vaultspec_rag/api.py`.
- [x] `W03.P07.S30` - add unit tests asserting the readiness snapshot is bounded and read-only across the three dependency dimensions; `src/vaultspec_rag/tests/test_readiness.py`.

### Phase `W03.P08` - readiness CLI and MCP adapters

Expose the readiness reporter through a CLI verb and the MCP tool surface as thin adapters over the shared service-domain behavior, in human and JSON modes.

- [x] `W03.P08.S31` - add a server doctor readiness CLI verb that renders the shared readiness snapshot in human and JSON modes as a thin adapter; `src/vaultspec_rag/cli/_service_status.py`.
- [x] `W03.P08.S32` - register the readiness verb under the server command group; `src/vaultspec_rag/cli/_app.py`.
- [x] `W03.P08.S33` - add a get_readiness MCP tool that returns the same readiness snapshot envelope as the CLI verb; `src/vaultspec_rag/server/_routes.py`.
- [x] `W03.P08.S34` - add tests asserting the CLI readiness verb and MCP readiness tool return the same bounded snapshot in both modes; `src/vaultspec_rag/tests/test_cli.py`.

## Wave `W04` - documentation reframe and persona validation

Reframe getting-started and CLI help from 'local-first, server optional' to 'server-first, local explicit', describing local as the minimal/CI/air-gapped alternative, then close the feature with a manual operator-persona validation that exercises the real command surface in human and JSON modes per the cli-operability-needs-persona-tests rule. Depends on W01-W03 because it documents and validates the behaviors they deliver.

### Phase `W04.P09` - documentation reframe

Reframe getting-started, installation, service-mode docs, and CLI help to server-first standard with local as the explicit minimal alternative.

- [ ] `W04.P09.S35` - reframe the getting-started flow to install-then-setup with a server-backed RAG as the standard path and local-only as the minimal alternative; `docs/getting-started.md`.
- [ ] `W04.P09.S36` - rewrite the installation doc to describe default provisioning of torch, models, and the qdrant binary plus the --local-only opt-out; `docs/installation.md`.
- [ ] `W04.P09.S37` - reframe the service-mode doc from local-first server-optional to server-first local-explicit and document the readiness verb; `docs/service-mode.md`.
- [ ] `W04.P09.S38` - update the bundled RAG rule prose to describe server mode as the default backend and local-only as the explicit opt-out; `.vaultspec/rules/rules/vaultspec-rag.builtin.md`.
- [ ] `W04.P09.S39` - update the start and install command help text to describe the server-first default and the local-only escape hatch; `src/vaultspec_rag/cli/_service_lifecycle.py`.

### Phase `W04.P10` - persona validation and codification

Run a manual operator-persona validation across the real command surface in human and JSON modes and record the outcome, closing the CLI operability loop.

- [ ] `W04.P10.S40` - run the operator-persona validation exercising default server start, --local-only start, setup provisioning, and the readiness verb in human and JSON modes and record observed confusion or acceptance; `.vault/audit/2026-06-13-server-first-default-audit.md`.
- [ ] `W04.P10.S41` - run the full unit and integration suite confirming the server-first default, provisioning, and readiness changes pass; `src/vaultspec_rag/tests/test_cli.py`.
- [ ] `W04.P10.S42` - update the human CLI documentation so the readiness verb and install opt-out flags match the live command surface; `docs/cli.md`.

## Description

This plan executes the two accepted ADRs that reframe vaultspec-rag from local-first to server-first. The server-first-default ADR establishes that server mode is the assumed RAG backend (an adversarial A/B on a 469k-chunk corpus measured a ~54x end-to-end win and the quality audit confirmed correct, robust results), that local mode stays a first-class single-flag opt-out, that the distribution wheel must remain pure-Python so the Qdrant binary is never bundled, and that failure when the server cannot start must be loud and actionable. The provisioning-setup ADR consolidates the three fragmented provisioning mechanisms (torch CUDA wheels, Hugging Face models, the Qdrant binary) behind one opt-out setup front door that reuses the existing per-dependency backends, reports each step through the shared sync vocabulary, stays idempotent, supports dry-run, surfaces the heterogeneous torch step honestly as configured-with-sync-pending, and is mirrored by a bounded read-only readiness verb.

The current state grounds every Step. The runtime default lives in `config.py` as `qdrant_server` defaulting to `False`; `server/_lifespan.py` already supervises the Qdrant child when that flag is on and the existing backend-aware store locking and per-root namespaced collections carry over unchanged, so W01 only flips the default and adds the local-only selection knob rather than re-implementing supervision. The setup surface lives in `commands/_install.py` (orchestrator) and `cli/_install.py` (Typer wrapper), with the torch configurator in `torch_config/`, the model warmup path in `cli/_service_lifecycle.py`, and the Qdrant provisioner in `qdrant_runtime/_provision.py`; W02 adds a front-door orchestrator over those backends, never a rewrite. The readiness verb (W03) is built in the service domain (`api.py`) first so the CLI and MCP adapt to shared behavior rather than duplicating it, honoring the service-domain-owns-operability rule, and stays bounded and read-only per operator-views-are-bounded. W04 reframes the docs and closes with the mandatory operator-persona validation required by the cli-operability-needs-persona-tests rule. The verify-before-execute security contract in `qdrant_runtime/_supervise.py` is preserved untouched, and no Step bundles the binary, honoring pinned-binaries-verify-before-execute and the pure-Python wheel constraint.

## Steps

## Parallelization

Waves are sequenced: W01 establishes the runtime default that W02 provisions for, W03 reports on, and W04 documents, so each Wave must land before the next begins. Within W01, P01 (config) is the foundation P02 and P03 both depend on; P02 (service startup) and P03 (CLI start surface) read the effective server mode P01 introduces and can be developed in parallel once P01 lands, but both should be verified together because the CLI flag and the daemon-side selection are two ends of one contract. Within W02, P04 (front-door orchestrator) must precede P05 (CLI wiring) and P06 (report and tests); P05 and P06 can proceed in parallel once P04 exists. Within W03, P07 (service-domain reporter) must precede P08 (CLI and MCP adapters) because the adapters render the shared snapshot P07 produces. Within W04, P09 (docs reframe) can proceed in parallel with the test and reference Steps of P10, but the operator-persona validation Step (S40) is gated on every prior Wave landing because it exercises the whole real command surface; it is the last Step to run.

## Verification

The plan is complete when every Step is closed (`- [x]`). Concrete success criteria:

- W01: `vaultspec-rag server start` with no flags starts in server mode and supervises the Qdrant child; `server start --local-only` selects the on-disk store; a missing binary on the default path produces a loud, actionable failure naming the install command and the `--local-only` escape hatch; unit and integration tests for the default flip and the opt-out pass.
- W02: a default `vaultspec-rag install` provisions torch (reporting configured-with-sync-pending), models, and the Qdrant binary, each through the shared sync vocabulary; `--local-only` skips the binary and selects the local runtime; per-dependency skip flags work; re-running a satisfied dependency is an `unchanged` no-op with no network; `--dry-run` previews without writing; the verify-before-execute contract is preserved and no Step bundles the binary.
- W03: the readiness verb and its MCP tool return the same bounded, read-only snapshot in human and JSON modes, reporting torch CUDA availability, model presence, and the Qdrant binary resolution source plus supervised-server liveness, with no model load forced.
- W04: getting-started, installation, service-mode docs, the bundled RAG rule, and CLI help describe server-first as standard and local-only as the explicit minimal alternative; the full test suite passes; the human CLI reference matches the live surface; and the operator-persona validation has been run across server start, `--local-only` start, setup provisioning, and the readiness verb in human and JSON modes with the outcome recorded in the feature audit.

The single-GPU and zero-mocks test mandates carry over unchanged. Code review via vaultspec-code-review is mandatory after execution.
