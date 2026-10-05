---
tags:
  - '#plan'
  - '#qdrant-provisioning-trust'
date: '2026-10-05'
tier: L1
related:
  - '[[2026-10-05-qdrant-provisioning-trust-adr]]'
  - '[[2026-06-12-qdrant-server-provisioning-adr]]'
  - '[[2026-06-13-provisioning-setup-adr]]'
  - '[[2026-09-04-cuda-provisioning-adr]]'
  - '[[2026-06-13-server-first-default-adr]]'
  - '[[2026-10-05-qdrant-provisioning-trust-audit]]'
  - '[[2026-10-05-qdrant-provisioning-trust-research]]'
modified: '2026-10-05'
body_schema: body-v2
body_hash: 'sha256:80c88251f1473d8b5fbc42e7a9383c5b62350c72d2fb9d39472910c666a64196'
---

# `qdrant-provisioning-trust` plan

## Description

Approved 2026-10-05

Basis: the user reviewed the audit findings in conversation on 2026-10-05, directed that `server start` provision the Qdrant binary the way model weights are provisioned, that sources use official channels with prefixed environment overrides defaulted in core settings, that client installations never provision anything, and that each issue be delegated to its own agent; they then selected "ADR and plan first, then dispatch" when asked how to proceed.

This plan executes `2026-10-05-qdrant-provisioning-trust-adr`, which is grounded in `2026-10-05-qdrant-provisioning-trust-audit` and refines `2026-06-12-qdrant-server-provisioning-adr` and `2026-06-13-provisioning-setup-adr`. Decision coverage: every Step sits inside that ADR. S01, S02, and S08 implement its resolution and execution-trust decisions (D2, D3). S03, S04, and S05 implement its atomic-install and serialisation constraints. S09, S10, and S11 implement source configuration (D4). S06, S07, S12, and S13 implement the consent model and the single front door (D1) under the client-role constraint from `2026-09-04-cuda-provisioning-adr`.

Extended 2026-10-05. Basis: after eight Steps had closed, the user wrote that no hole may be left and asked for review, continuation, and architecture hardening, then listed documentation, provisioning command descriptions, an architecture review, hostile reviews, and tests for network degradation and exhausted disk space. S15 to S19 implement the operator-route, offline-install, execution-binding, and model-revision rulings added to `2026-10-05-qdrant-provisioning-trust-adr` (D6, D7, D8). S20 restores two gates that were already red on this branch. S21 and S22 cover failure-condition testing and process documentation.

## Steps

- [x] `S01` - commit a per-asset executable digest table for the pinned release with a guard that it covers every selectable asset; `src/vaultspec_rag/qdrant_runtime/_constants.py`.
- [x] `S02` - remove the PATH resolution tier and require the operator binary setting to name an absolute regular file; `src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [x] `S03` - stage the download and extraction, verify archive and executable digests, then replace atomically with the manifest written last and a prior install left intact on any failure; `src/vaultspec_rag/qdrant_runtime/_provision.py`.
- [x] `S04` - hash the installed executable when classifying install state so the upgrade path repairs a mismatched install; `src/vaultspec_rag/qdrant_runtime/_provision.py`.
- [x] `S05` - serialise provisioning across processes, bound the whole download with a deadline, guard the staging file against links, and report an unsupported platform as a failed outcome; `src/vaultspec_rag/qdrant_runtime/_provision.py`.
- [x] `S06` - decide the installation role before any provisioning on server start and prove that a client start, install, and warmup download nothing; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `S07` - provision the binary by default on a host server start behind the auto-provision switch and its opt-out flag, and announce an operator binary on the console; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `S08` - verify the executable through the shared native-binary verifier inside every spawn, fail closed on a missing digest, and label operator binaries on status surfaces; `src/vaultspec_rag/qdrant_runtime/_supervise.py and _resolve.py`.
- [x] `S09` - add the auto-provision switch, release base URL, and download-host settings with official defaults and prefixed environment overrides kept out of workspace files; `src/vaultspec_rag/config/ and docs/configuration.md`.
- [x] `S10` - route the downloader URL and redirect host pin through the source settings and delete the superseded constants and the unused API host; `src/vaultspec_rag/qdrant_runtime/_provision.py and _constants.py`.
- [x] `S11` - add prefixed overrides for the model hub endpoint and the CUDA wheel index with their current values as defaults, or record the collision that prevents one; `src/vaultspec_rag/config/ and src/vaultspec_rag/torch_config/_index.py`.
- [x] `S12` - collapse model fetching to one implementation shared by install, server warmup, and the start preflight, and ensure models through it before the daemon spawns; `src/vaultspec_rag/commands/_provision.py, cli/_service_lifecycle.py and cli/_service_start.py`.
- [x] `S13` - correct the daemon-provisioning prose and bring the installation, CLI, and backend guides in line with automatic host provisioning and the removed PATH tier; `src/vaultspec_rag/server/_lifespan.py and docs/`.
- [x] `S14` - select the static musl asset for Linux x64 and verify an existing install against the committed executable digest of the asset its manifest names; `src/vaultspec_rag/qdrant_runtime/_resolve.py and _constants.py`.
- [ ] `S15` - add the operator binary digest setting and resolve an operator binary only from the path and digest settings together, dropping the manifest-registered source; `src/vaultspec_rag/config/ and src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [ ] `S16` - replace operator registration with an offline install from a local official archive verified against the committed archive and executable digests; `src/vaultspec_rag/qdrant_runtime/_provision.py`.
- [ ] `S17` - replace the install verb's binary option with a local archive option and report an operator-claiming manifest as invalid with the two supported routes; `src/vaultspec_rag/cli/_service_qdrant.py and docs/`.
- [x] `S18` - pass the verified path as the executable, hold the file against replacement between hashing and process creation where the platform allows, hash the managed install in readiness, and extract spawn trust out of the supervisor module; `src/vaultspec_rag/qdrant_runtime/ and src/vaultspec_rag/_readiness.py`.
- [ ] `S19` - commit revisions for the default dense and reranker models with prefixed revision settings, used by every fetch and load, and report an unpinned operator model on status; `src/vaultspec_rag/config/, _sparse_profile.py, _model_cache.py and the model load and fetch sites`.
- [x] `S20` - restore the two gates that are red on this branch: the monitor test typing and the undeclared substitution site; `src/vaultspec_rag/tests/test_monitor_inventory.py, test_monitor_browser.py, test_document_index_symlinks.py and test_substitution_discipline.py`.
- [x] `S21` - refuse a download that cannot fit with a free-space preflight, and test the binary downloader and the model fetch against stalled, slow, reset, truncated, refused, and untrusted connections and against exhausted disk space, each ending in a failed outcome that leaves a prior install intact; `src/vaultspec_rag/qdrant_runtime/_provision.py, commands/_model_fetch.py and their tests`.
- [ ] `S22` - describe the provisioning process end to end in the guides and make every provisioning command's help state what it fetches, from where, how it is verified, how it is overridden, and how it fails; `docs/, README.md and the provisioning command help text under src/vaultspec_rag/cli/`.
- [ ] `S23` - commit a per-file digest manifest for each default model at its pinned revision, verify the snapshot against it after fetch and before every load including the remote-code files that are actually imported, and load weights from safetensors only; `src/vaultspec_rag/_model_cache.py, _sparse_profile.py, _sparse_encoder.py, embeddings.py and the model fetch engine`.
- [ ] `S24` - collapse the two kill-descendants, kill, wait, and confirm compositions around a child process into one shared teardown; `src/vaultspec_rag/commands/_model_download.py, indexer/_preprocess_runner.py and _process_probe.py`.
- [ ] `S25` - run every child interpreter the package spawns in safe-path mode so the working directory can never shadow the package or its dependencies, with a source guard over all spawn sites; `src/vaultspec_rag/commands/_model_download.py, cli/_process.py, operator_state/_environment_probe.py, _process_probe.py and the MCP launch writers`.
- [ ] `S26` - decide the backend once from the effective settings with flags as overrides, for both the start preflight and the daemon environment, so a persisted or exported local-only or remote-server choice is honoured; `src/vaultspec_rag/cli/_service_start.py and cli/_process.py`.
- [ ] `S27` - gate every provisioning surface and every readiness and status remedy on one judgement of whether this environment can run the service, and write no marker or directory before it; `src/vaultspec_rag/commands/_provision.py, _readiness.py, operator_state/ and cli/_service_qdrant.py`.
- [ ] `S28` - resolve the monitor, nvidia-smi, and uv from absolute locations outside the working directory through one helper, and pin the daemon's working directory; `src/vaultspec_rag/monitor_process.py, operator_state/_hardware.py, commands/_tool_torch.py, commands/_uv_sync.py and cli/_process.py`.
- [ ] `S29` - judge a version directory with one classifier shared by resolver and provisioner, heal a manifest-less install whose executable matches a committed digest, and name full commands in every remedy; `src/vaultspec_rag/qdrant_runtime/_provision.py and _resolve.py`.
- [ ] `S30` - end an interrupted foreground fetch promptly with one interrupted envelope on start and the install verb, carry next actions and one failure code in JSON envelopes, and give warmup a JSON mode; `src/vaultspec_rag/cli/_service_start.py, _service_qdrant.py, _service_lifecycle.py and commands/`.
- [ ] `S31` - bound every network call of the model fetch including the size query, add a whole-operation deadline setting, share one contention budget across repositories, classify local cache faults with their own remedy, and replace the substituted start-step tests with real ones; `src/vaultspec_rag/commands/_model_fetch.py, _hub_failure.py, config/ and tests/test_start_provisioning.py`.
- [ ] `S32` - stop counting a restart refused before any spawn as the one heartbeat restart, word a transient hold failure as such, and name stop then start on every surface that reports a dead server; `src/vaultspec_rag/qdrant_runtime/_supervise.py, _spawn_trust.py, server/_lifecycle.py and the status labels`.

## Parallelization

Four workers run in parallel in one working tree with disjoint write ownership. A file is edited only by its owner; a worker that needs a change in another worker's file asks the owner by message.

- Execution trust: S01, S02, S08, S14. Owns `src/vaultspec_rag/qdrant_runtime/_constants.py`, `_resolve.py`, `_supervise.py`, and `src/vaultspec_rag/tests/test_qdrant_runtime.py`.
- Install integrity: S03, S04, S05, S10. Owns `src/vaultspec_rag/qdrant_runtime/_provision.py` and `src/vaultspec_rag/tests/test_provision.py`.
- Sources and settings: S09, S11. Owns `src/vaultspec_rag/config/`, `src/vaultspec_rag/torch_config/`, and `docs/configuration.md`.
- Start flow: S06, S07, S12, S13. Owns `src/vaultspec_rag/cli/_service_start.py`, `cli/_service_lifecycle.py`, `cli/_service_qdrant.py`, `src/vaultspec_rag/commands/`, `src/vaultspec_rag/server/_lifespan.py`, and the remaining `docs/` guides.

Hard ordering: S01 lands before S03, S08, and S14 consume the table. S09 lands before S07 and S10 read the settings. S10 finishes with the constants owner deleting the superseded names once the downloader no longer imports them. S13 is last. New test files belong to the worker that creates them. Each worker commits its own paths by explicit pathspec on the current branch; nobody pushes or merges. Workers do not touch the vault; the orchestrator closes Steps and writes the ledger from their reports.

Extension. Execution trust takes S15 (resolution half) and S18. Sources and settings takes S15 (settings half, landed jointly with its reader as S09 was) and S19, and for S19 owns `src/vaultspec_rag/_sparse_profile.py`, `_model_cache.py`, and the model load sites. Install integrity takes S16 and the binary half of S21. Start flow takes S17, the model half of S21, and S22, with S13 and S22 last. A fifth worker takes S20 and owns only the four test files it names. S16 follows S05; S17 follows S16; S22 follows every behaviour change.

## Verification

- Lint, format, strict type-check, and the covering CPU-lane tests pass for every touched file, with each gate's exit code captured on its own.

- Each new guard is shown failing on its named assertion with the guard broken, then passing restored, in one sequence, and both directions are recorded in the commit message.

- A working-directory `qdrant` file is never resolved; a managed install with a missing or mismatched executable digest is refused at first spawn and at restart; the upgrade verb repairs it.

- A failed download or an interrupted extraction leaves a previous install runnable.

- With an isolated status directory and no binary, a host start reaches provisioning without the consent flag, the opt-out restores the instruction failure, and a client start, install, and warmup perform no download.

- The source settings default to the official release channel, accept a prefixed override, reject a non-HTTPS value, and are not readable from a workspace file.

- The six committed archive digests and the new executable digests are reproduced from the pinned host by the method recorded with the table.

- The integration tier borrows the GPU from the resident service; if that service is not running, the tier is reported as not run rather than claimed.

- One integrated review against `2026-10-05-qdrant-provisioning-trust-adr` passes before the work is reported complete.

- Extension: no process is created for the server binary without a digest check, proven for a managed install, an operator binary, a restart, and a retry; a manifest claiming an operator source is not honoured.

- An offline install from a local official archive passes the same checks as a download and makes no network request.

- Each degraded-network and exhausted-space condition ends in one failed outcome with a remedy, a non-zero exit, no staging residue, and a prior install still runnable.

- A live proof in an isolated status directory downloads the pinned archive from the official host, verifies it, starts the real binary through the supervisor, and stops it.

- Three hostile reviews - trust and supply chain, failure and concurrency, client and command contract - and one integrated review against the decision are recorded in the rolling audit, and every critical or high finding is resolved before completion is reported.
