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
modified: '2026-10-05'
body_schema: body-v2
body_hash: 'sha256:5907dfc9f12d399fb4c83cb5e94bd26f08528fe1d52750a64ef8665688c4dba5'
---

# `qdrant-provisioning-trust` plan

## Description

Approved 2026-10-05

Basis: the user reviewed the audit findings in conversation on 2026-10-05, directed that `server start` provision the Qdrant binary the way model weights are provisioned, that sources use official channels with prefixed environment overrides defaulted in core settings, that client installations never provision anything, and that each issue be delegated to its own agent; they then selected "ADR and plan first, then dispatch" when asked how to proceed.

This plan executes `2026-10-05-qdrant-provisioning-trust-adr`, which is grounded in `2026-10-05-qdrant-provisioning-trust-audit` and refines `2026-06-12-qdrant-server-provisioning-adr` and `2026-06-13-provisioning-setup-adr`. Decision coverage: every Step sits inside that ADR. S01, S02, and S08 implement its resolution and execution-trust decisions (D2, D3). S03, S04, and S05 implement its atomic-install and serialisation constraints. S09, S10, and S11 implement source configuration (D4). S06, S07, S12, and S13 implement the consent model and the single front door (D1) under the client-role constraint from `2026-09-04-cuda-provisioning-adr`.

## Steps

- [ ] `S01` - commit a per-asset executable digest table for the pinned release with a guard that it covers every selectable asset; `src/vaultspec_rag/qdrant_runtime/_constants.py`.
- [ ] `S02` - remove the PATH resolution tier and require the operator binary setting to name an absolute regular file; `src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [ ] `S03` - stage the download and extraction, verify archive and executable digests, then replace atomically with the manifest written last and a prior install left intact on any failure; `src/vaultspec_rag/qdrant_runtime/_provision.py`.
- [ ] `S04` - hash the installed executable when classifying install state so the upgrade path repairs a mismatched install; `src/vaultspec_rag/qdrant_runtime/_provision.py`.
- [ ] `S05` - serialise provisioning across processes, bound the whole download with a deadline, guard the staging file against links, and report an unsupported platform as a failed outcome; `src/vaultspec_rag/qdrant_runtime/_provision.py`.
- [ ] `S06` - decide the installation role before any provisioning on server start and prove that a client start, install, and warmup download nothing; `src/vaultspec_rag/cli/_service_start.py`.
- [ ] `S07` - provision the binary by default on a host server start behind the auto-provision switch and its opt-out flag, and announce an operator binary on the console; `src/vaultspec_rag/cli/_service_start.py`.
- [ ] `S08` - verify the executable through the shared native-binary verifier inside every spawn, fail closed on a missing digest, and label operator binaries on status surfaces; `src/vaultspec_rag/qdrant_runtime/_supervise.py and _resolve.py`.
- [ ] `S09` - add the auto-provision switch, release base URL, and download-host settings with official defaults and prefixed environment overrides kept out of workspace files; `src/vaultspec_rag/config/ and docs/configuration.md`.
- [ ] `S10` - route the downloader URL and redirect host pin through the source settings and delete the superseded constants and the unused API host; `src/vaultspec_rag/qdrant_runtime/_provision.py and _constants.py`.
- [ ] `S11` - add prefixed overrides for the model hub endpoint and the CUDA wheel index with their current values as defaults, or record the collision that prevents one; `src/vaultspec_rag/config/ and src/vaultspec_rag/torch_config/_index.py`.
- [ ] `S12` - collapse model fetching to one implementation shared by install, server warmup, and the start preflight, and ensure models through it before the daemon spawns; `src/vaultspec_rag/commands/_provision.py, cli/_service_lifecycle.py and cli/_service_start.py`.
- [ ] `S13` - correct the daemon-provisioning prose and bring the installation, CLI, and backend guides in line with automatic host provisioning and the removed PATH tier; `src/vaultspec_rag/server/_lifespan.py and docs/`.

## Parallelization

Four workers run in parallel in one working tree with disjoint write ownership. A file is edited only by its owner; a worker that needs a change in another worker's file asks the owner by message.

- Execution trust: S01, S02, S08. Owns `src/vaultspec_rag/qdrant_runtime/_constants.py`, `_resolve.py`, `_supervise.py`, and `src/vaultspec_rag/tests/test_qdrant_runtime.py`.
- Install integrity: S03, S04, S05, S10. Owns `src/vaultspec_rag/qdrant_runtime/_provision.py` and `src/vaultspec_rag/tests/test_provision.py`.
- Sources and settings: S09, S11. Owns `src/vaultspec_rag/config/`, `src/vaultspec_rag/torch_config/`, and `docs/configuration.md`.
- Start flow: S06, S07, S12, S13. Owns `src/vaultspec_rag/cli/_service_start.py`, `cli/_service_lifecycle.py`, `cli/_service_qdrant.py`, `src/vaultspec_rag/commands/`, `src/vaultspec_rag/server/_lifespan.py`, and the remaining `docs/` guides.

Hard ordering: S01 lands before S03 and S08 consume the table. S09 lands before S07 and S10 read the settings. S10 finishes with the constants owner deleting the superseded names once the downloader no longer imports them. S13 is last. New test files belong to the worker that creates them. Each worker commits its own paths by explicit pathspec on the current branch; nobody pushes or merges.

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
