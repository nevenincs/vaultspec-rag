---
generated: true
tags:
  - '#index'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
related:
  - '[[2026-06-12-qdrant-server-provisioning-P01-S01]]'
  - '[[2026-06-12-qdrant-server-provisioning-P01-S02]]'
  - '[[2026-06-12-qdrant-server-provisioning-P01-S03]]'
  - '[[2026-06-12-qdrant-server-provisioning-P02-S04]]'
  - '[[2026-06-12-qdrant-server-provisioning-P02-S05]]'
  - '[[2026-06-12-qdrant-server-provisioning-P03-S06]]'
  - '[[2026-06-12-qdrant-server-provisioning-P03-S07]]'
  - '[[2026-06-12-qdrant-server-provisioning-P04-S08]]'
  - '[[2026-06-12-qdrant-server-provisioning-P04-S09]]'
  - '[[2026-06-12-qdrant-server-provisioning-P05-S10]]'
  - '[[2026-06-12-qdrant-server-provisioning-P05-S11]]'
  - '[[2026-06-12-qdrant-server-provisioning-P05-S12]]'
  - '[[2026-06-12-qdrant-server-provisioning-P05-summary]]'
  - '[[2026-06-12-qdrant-server-provisioning-adr]]'
  - '[[2026-06-12-qdrant-server-provisioning-audit]]'
  - '[[2026-06-12-qdrant-server-provisioning-plan]]'
  - '[[2026-06-12-qdrant-server-provisioning-research]]'
---

# `qdrant-server-provisioning` feature index

Auto-generated index of all documents tagged with `#qdrant-server-provisioning`.

## Documents

### adr

- `2026-06-12-qdrant-server-provisioning-adr` - `qdrant-server-provisioning` adr: `qdrant server mode with binary provisioning` | (**status:** `accepted`)

### audit

- `2026-06-12-qdrant-server-provisioning-audit` - `qdrant-server-provisioning` Code Review

### exec

- `2026-06-12-qdrant-server-provisioning-P01-S01` - Create qdrant_runtime constants module with the pinned server version and the committed per-asset SHA256 map, plus config knobs for server toggle, port, binary, and storage dir
- `2026-06-12-qdrant-server-provisioning-P01-S02` - Implement platform-to-asset mapping and active-binary resolution ordered env var, provisioned dir, PATH
- `2026-06-12-qdrant-server-provisioning-P01-S03` - Implement host-pinned download, SHA256 verify before extraction, extraction, manifest, idempotent unchanged, and dry-run reporting in the sync vocabulary, with unit tests including the uv.lock minor-pin guard
- `2026-06-12-qdrant-server-provisioning-P02-S04` - Implement qdrant child supervision: loopback spawn with env-injected storage and ports, readyz poll with backoff, graceful terminate, and Windows kill-on-close Job Object
- `2026-06-12-qdrant-server-provisioning-P02-S05` - Namespace store collections per root in server mode via a stable short-hash prefix with instance-resolved collection names, unit-tested for stability and local-mode invariance
- `2026-06-12-qdrant-server-provisioning-P03-S06` - Spawn qdrant before model load in the service lifespan, publish the in-process server URL, stop qdrant last among data components, and add a qdrant block to health
- `2026-06-12-qdrant-server-provisioning-P03-S07` - Add qdrant liveness with one bounded auto-restart to the heartbeat, record the child PID in the service status file, and surface a qdrant block in the service-state read
- `2026-06-12-qdrant-server-provisioning-P04-S08` - Add the server qdrant command group with install (upgrade, dry-run, binary, json), bounded status, and yes-gated clean
- `2026-06-12-qdrant-server-provisioning-P04-S09` - Add server start --qdrant and --qdrant-auto-provision consent flags translated to daemon env, hard-failing with the exact install command when the binary is absent without consent
- `2026-06-12-qdrant-server-provisioning-P05-S10` - Integration test: provision the real binary, run a server-mode vault and code index plus hybrid search round trip on an ephemeral port with temp storage, assert per-root prefixes and clean child reaping
- `2026-06-12-qdrant-server-provisioning-P05-S11` - Run the concurrency benchmark against this worktree corpus in local and server modes and record the qdrant-phase delta
- `2026-06-12-qdrant-server-provisioning-P05-S12` - Run the operator persona pass over the qdrant CLI surface in human and JSON modes and record observations
- `2026-06-12-qdrant-server-provisioning-P05-summary` - `qdrant-server-provisioning` `P05` summary

### plan

- `2026-06-12-qdrant-server-provisioning-plan` - `qdrant-server-provisioning` `server mode with binary provisioning` plan

### research

- `2026-06-12-qdrant-server-provisioning-research` - `qdrant-server-provisioning` research: `qdrant binary provisioning and release pipeline`
