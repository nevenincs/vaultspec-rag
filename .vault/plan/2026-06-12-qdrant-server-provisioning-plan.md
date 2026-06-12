---
tags:
  - '#plan'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
tier: L2
related:
  - '[[2026-06-12-qdrant-server-provisioning-adr]]'
  - '[[2026-06-12-qdrant-server-provisioning-research]]'
---

# `qdrant-server-provisioning` `server mode with binary provisioning` plan

### Phase `P01` - Runtime package: constants, resolution, provisioning

Pin the server version and digests, resolve assets and binaries, and provision idempotently with dry-run support

- [x] `P01.S01` - Create qdrant_runtime constants module with the pinned server version and the committed per-asset SHA256 map, plus config knobs for server toggle, port, binary, and storage dir; `src/vaultspec_rag/qdrant_runtime/_constants.py, src/vaultspec_rag/config.py`.
- [x] `P01.S02` - Implement platform-to-asset mapping and active-binary resolution ordered env var, provisioned dir, PATH; `src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [x] `P01.S03` - Implement host-pinned download, SHA256 verify before extraction, extraction, manifest, idempotent unchanged, and dry-run reporting in the sync vocabulary, with unit tests including the uv.lock minor-pin guard; `src/vaultspec_rag/qdrant_runtime/_provision.py, src/vaultspec_rag/tests/test_qdrant_runtime.py`.

### Phase `P02` - Supervision and store namespacing

Spawn and reap the loopback qdrant child safely on all platforms and namespace per-root collections in server mode

- [x] `P02.S04` - Implement qdrant child supervision: loopback spawn with env-injected storage and ports, readyz poll with backoff, graceful terminate, and Windows kill-on-close Job Object; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [x] `P02.S05` - Namespace store collections per root in server mode via a stable short-hash prefix with instance-resolved collection names, unit-tested for stability and local-mode invariance; `src/vaultspec_rag/store.py, src/vaultspec_rag/tests/test_store.py`.

### Phase `P03` - Service lifecycle integration

Wire server mode into config, lifespan, heartbeat, health, and the service-state surface

- [x] `P03.S06` - Spawn qdrant before model load in the service lifespan, publish the in-process server URL, stop qdrant last among data components, and add a qdrant block to health; `src/vaultspec_rag/server/_lifespan.py, src/vaultspec_rag/server/_state.py`.
- [x] `P03.S07` - Add qdrant liveness with one bounded auto-restart to the heartbeat, record the child PID in the service status file, and surface a qdrant block in the service-state read; `src/vaultspec_rag/server/_lifecycle.py, src/vaultspec_rag/api.py`.

### Phase `P04` - CLI surface

Ship the server qdrant command group and the server start consent flags

- [ ] `P04.S08` - Add the server qdrant command group with install (upgrade, dry-run, binary, json), bounded status, and yes-gated clean; `src/vaultspec_rag/cli/_service_qdrant.py, src/vaultspec_rag/cli/_app.py`.
- [ ] `P04.S09` - Add server start --qdrant and --qdrant-auto-provision consent flags translated to daemon env, hard-failing with the exact install command when the binary is absent without consent; `src/vaultspec_rag/cli/_service_lifecycle.py, src/vaultspec_rag/cli/_process.py`.

### Phase `P05` - Validation: integration, benchmark, persona

Prove the real binary round trip, measure local versus server, and run the operator persona pass

- [ ] `P05.S10` - Integration test: provision the real binary, run a server-mode vault and code index plus hybrid search round trip on an ephemeral port with temp storage, assert per-root prefixes and clean child reaping; `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`.
- [ ] `P05.S11` - Run the concurrency benchmark against this worktree corpus in local and server modes and record the qdrant-phase delta; `.vault/exec/2026-06-12-qdrant-server-provisioning/`.
- [ ] `P05.S12` - Run the operator persona pass over the qdrant CLI surface in human and JSON modes and record observations; `.vault/exec/2026-06-12-qdrant-server-provisioning/`.

## Description

Implement the `2026-06-12-qdrant-server-provisioning-adr`: promote Qdrant server
mode to a supervised, provisioned topology. A new `qdrant_runtime` package pins the
server binary (1.18.2, SHA256-committed for all six release assets), resolves and
provisions it download-on-first-use, and supervises it as a loopback child of the
resident daemon with a Windows kill-on-close Job Object. The store gains per-root
namespaced collections in server mode; the service lifespan, heartbeat, health, and
service-state surfaces gain a qdrant block; the CLI gains a `server qdrant` group
and `server start --qdrant` consent flags. Grounded in the
`2026-06-12-qdrant-server-provisioning-research` design and the
`2026-06-12-serving-runtime-research` decision criteria; builds on the
`2026-06-12-service-concurrency-adr` backend-aware store locks.

## Steps

## Parallelization

Phases are sequential: P01 (constants/resolution/provisioning) feeds P02
(supervision needs a resolved binary; namespacing is independent but shares the
store edit window), P03 consumes both, P04 wraps the lifecycle in CLI flags, and
P05 validates the whole. Within P02, S04 and S05 touch disjoint files and could be
parallelised; everything else carries hard ordering. This run executes
single-agent, in order.

## Verification

- Unit suite green: asset resolution per platform, checksum mismatch deletes the
  partial and reports failed, pre-seeded provisioning reports unchanged with no
  network, dry-run writes nothing, the pinned server minor matches the locked
  qdrant-client minor parsed from `uv.lock`, and namespaced collection derivation
  is stable and absent in local mode.
- Integration test green on the real binary and real GPU: server-mode vault+code
  index and hybrid search round trip on an ephemeral loopback port with temp
  storage, two roots landing in differently prefixed collections on one server,
  shutdown reaping the child with no orphaned process.
- Benchmark evidence: `bench_concurrency` qdrant-phase delta between local and
  server modes against this worktree corpus, recorded in the exec summary.
- Operator persona pass over `server qdrant install --dry-run`, `install`,
  `status`, `status --json`, `server start --qdrant`, `server status`, and a real
  search, with observations recorded per the `cli-operability-needs-persona-tests`
  rule.
- Pre-commit hooks (ruff, ty, complexity, mdformat) pass on every commit; code
  review signs off before the plan closes.
