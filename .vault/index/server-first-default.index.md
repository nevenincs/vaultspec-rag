---
generated: true
tags:
  - '#index'
  - '#server-first-default'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:a28a8f8d546758c202a30ba416bfe68db3a0a203b2dee6242c53f0ed63f10c6e'
related:
  - '[[2026-06-13-server-first-default-W01-P01-S01]]'
  - '[[2026-06-13-server-first-default-W01-P01-S02]]'
  - '[[2026-06-13-server-first-default-W01-P01-S03]]'
  - '[[2026-06-13-server-first-default-W01-P01-S04]]'
  - '[[2026-06-13-server-first-default-W01-P02-S05]]'
  - '[[2026-06-13-server-first-default-W01-P02-S06]]'
  - '[[2026-06-13-server-first-default-W01-P02-S07]]'
  - '[[2026-06-13-server-first-default-W01-P02-S08]]'
  - '[[2026-06-13-server-first-default-W01-P03-S09]]'
  - '[[2026-06-13-server-first-default-W01-P03-S10]]'
  - '[[2026-06-13-server-first-default-W01-P03-S11]]'
  - '[[2026-06-13-server-first-default-W01-P03-S12]]'
  - '[[2026-06-13-server-first-default-W02-P04-S13]]'
  - '[[2026-06-13-server-first-default-W02-P04-S14]]'
  - '[[2026-06-13-server-first-default-W02-P04-S15]]'
  - '[[2026-06-13-server-first-default-W02-P04-S16]]'
  - '[[2026-06-13-server-first-default-W02-P04-S17]]'
  - '[[2026-06-13-server-first-default-W02-P05-S18]]'
  - '[[2026-06-13-server-first-default-W02-P05-S19]]'
  - '[[2026-06-13-server-first-default-W02-P05-S20]]'
  - '[[2026-06-13-server-first-default-W02-P05-S21]]'
  - '[[2026-06-13-server-first-default-W02-P06-S22]]'
  - '[[2026-06-13-server-first-default-W02-P06-S23]]'
  - '[[2026-06-13-server-first-default-W02-P06-S24]]'
  - '[[2026-06-13-server-first-default-W02-P06-S25]]'
  - '[[2026-06-13-server-first-default-W03-P07-S26]]'
  - '[[2026-06-13-server-first-default-W03-P07-S27]]'
  - '[[2026-06-13-server-first-default-W03-P07-S28]]'
  - '[[2026-06-13-server-first-default-W03-P07-S29]]'
  - '[[2026-06-13-server-first-default-W03-P07-S30]]'
  - '[[2026-06-13-server-first-default-W03-P08-S31]]'
  - '[[2026-06-13-server-first-default-W03-P08-S32]]'
  - '[[2026-06-13-server-first-default-W03-P08-S33]]'
  - '[[2026-06-13-server-first-default-W03-P08-S34]]'
  - '[[2026-06-13-server-first-default-W04-P09-S35]]'
  - '[[2026-06-13-server-first-default-W04-P09-S36]]'
  - '[[2026-06-13-server-first-default-W04-P09-S37]]'
  - '[[2026-06-13-server-first-default-W04-P09-S38]]'
  - '[[2026-06-13-server-first-default-W04-P09-S39]]'
  - '[[2026-06-13-server-first-default-W04-P10-S42]]'
  - '[[2026-06-13-server-first-default-W04-P10-summary]]'
  - '[[2026-06-13-server-first-default-adr]]'
  - '[[2026-06-13-server-first-default-audit]]'
  - '[[2026-06-13-server-first-default-plan]]'
  - '[[2026-07-27-server-first-default-grounding-research]]'
---

# `server-first-default` feature index

Auto-generated index of all documents tagged with `#server-first-default`.

## Documents

### adr

- `2026-06-13-server-first-default-adr` - `server-first-default` adr: `server mode is the default rag backend` | (**status:** `accepted`)

### audit

- `2026-06-13-server-first-default-audit` - `server-first-default` audit: `server-first operator persona validation`

### exec

- `2026-06-13-server-first-default-W01-P01-S01` - flip the qdrant_server default from False to True in the RAG defaults so server mode is the assumed backend
- `2026-06-13-server-first-default-W01-P01-S02` - add the LOCAL_ONLY env var member and its \_ENV_OVERRIDE_MAP entry so a single knob selects the local backend across config resolution
- `2026-06-13-server-first-default-W01-P01-S03` - add a local_only RAG default and resolve effective server mode as qdrant_server and not local_only so local-only deterministically wins
- `2026-06-13-server-first-default-W01-P01-S04` - add unit tests asserting the server-mode default and the local-only override precedence across env and default resolution
- `2026-06-13-server-first-default-W01-P02-S05` - make service_lifespan select server mode by default and use the local store only when local-only is set, reading effective server mode from config
- `2026-06-13-server-first-default-W01-P02-S06` - convert the qdrant child startup failure into a loud, actionable startup abort that names the install command and the --local-only escape hatch
- `2026-06-13-server-first-default-W01-P02-S07` - surface the loud server-start failure remediation in the start-supervised entry point error message preserving verify-before-execute
- `2026-06-13-server-first-default-W01-P02-S08` - add integration tests for the server-first default startup path and the local-only opt-out startup path
- `2026-06-13-server-first-default-W01-P03-S09` - add a --local-only flag to server start that selects the local backend and reframe the existing --qdrant flag as the redundant explicit-server opt-in
- `2026-06-13-server-first-default-W01-P03-S10` - translate the --local-only start flag into the VAULTSPEC_RAG_LOCAL_ONLY daemon env, leaving operator-set env untouched when unset
- `2026-06-13-server-first-default-W01-P03-S11` - default the qdrant-binary pre-start guard to run by default and skip it under --local-only so a default start fails fast on a missing binary
- `2026-06-13-server-first-default-W01-P03-S12` - add CLI tests covering --local-only env translation, the default server-mode start, and the missing-binary loud-failure path
- `2026-06-13-server-first-default-W02-P04-S13` - create a provisioning front-door module that orchestrates torch, model, and qdrant provisioning and returns a heterogeneous per-dependency result
- `2026-06-13-server-first-default-W02-P04-S14` - wrap the torch configurator step in the front door so it reports configured-with-sync-pending through the shared sync vocabulary
- `2026-06-13-server-first-default-W02-P04-S15` - add a model-ensure provisioning step that reuses the warmup snapshot-download path and reports cached versus downloaded idempotently
- `2026-06-13-server-first-default-W02-P04-S16` - add a qdrant-binary provisioning step that delegates to the existing provisioner and maps its action onto the shared sync vocabulary
- `2026-06-13-server-first-default-W02-P04-S17` - export the front-door orchestrator from the commands package public surface
- `2026-06-13-server-first-default-W02-P05-S18` - call the provisioning front door by default from install_run and thread its result into the install report
- `2026-06-13-server-first-default-W02-P05-S19` - add --local-only to the install command so it skips the qdrant binary and selects the local runtime default
- `2026-06-13-server-first-default-W02-P05-S20` - add per-dependency skip flags for torch, models, and qdrant to the install command for finer opt-out than --local-only
- `2026-06-13-server-first-default-W02-P05-S21` - honor --local-only in install_run by writing the local-only runtime selection so the setup choice persists to runtime
- `2026-06-13-server-first-default-W02-P06-S22` - extend InstallReport with per-dependency provisioning outcomes and render them honestly in the human and JSON report
- `2026-06-13-server-first-default-W02-P06-S23` - render the heterogeneous provisioning outcomes in the install report renderer including the torch sync-pending wording
- `2026-06-13-server-first-default-W02-P06-S24` - add tests for front-door idempotency, dry-run preview, and the local-only binary skip on the provisioning orchestrator
- `2026-06-13-server-first-default-W02-P06-S25` - add an integration test for the default install provisioning path reporting heterogeneous per-dependency outcomes
- `2026-06-13-server-first-default-W03-P07-S26` - add a get_readiness facade function that aggregates the bounded per-dependency readiness snapshot in the service domain
- `2026-06-13-server-first-default-W03-P07-S27` - report torch CUDA availability as a readiness dimension without forcing model load
- `2026-06-13-server-first-default-W03-P07-S28` - report model presence by checking the HuggingFace cache for the configured dense, sparse, and reranker repos
- `2026-06-13-server-first-default-W03-P07-S29` - report the qdrant binary resolution source and supervised-server liveness by reading the qdrant runtime state
- `2026-06-13-server-first-default-W03-P07-S30` - add unit tests asserting the readiness snapshot is bounded and read-only across the three dependency dimensions
- `2026-06-13-server-first-default-W03-P08-S31` - add a server doctor readiness CLI verb that renders the shared readiness snapshot in human and JSON modes as a thin adapter
- `2026-06-13-server-first-default-W03-P08-S32` - register the readiness verb under the server command group
- `2026-06-13-server-first-default-W03-P08-S33` - add a get_readiness MCP tool that returns the same readiness snapshot envelope as the CLI verb
- `2026-06-13-server-first-default-W03-P08-S34` - add tests asserting the CLI readiness verb and MCP readiness tool return the same bounded snapshot in both modes
- `2026-06-13-server-first-default-W04-P09-S35` - reframe the getting-started flow to install-then-setup with a server-backed RAG as the standard path and local-only as the minimal alternative
- `2026-06-13-server-first-default-W04-P09-S36` - rewrite the installation doc to describe default provisioning of torch, models, and the qdrant binary plus the --local-only opt-out
- `2026-06-13-server-first-default-W04-P09-S37` - reframe the service-mode doc from local-first server-optional to server-first local-explicit and document the readiness verb
- `2026-06-13-server-first-default-W04-P09-S38` - update the bundled RAG rule prose to describe server mode as the default backend and local-only as the explicit opt-out
- `2026-06-13-server-first-default-W04-P09-S39` - update the start and install command help text to describe the server-first default and the local-only escape hatch
- `2026-06-13-server-first-default-W04-P10-S42` - update the human CLI documentation so the readiness verb and install opt-out flags match the live command surface
- `2026-06-13-server-first-default-W04-P10-summary` - `server-first-default` `W04.P10` summary

### plan

- `2026-06-13-server-first-default-plan` - `server-first-default` plan

### research

- `2026-07-27-server-first-default-grounding-research` - `server-first-default` research: `Grounding`
