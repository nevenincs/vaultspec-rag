---
tags:
  - '#audit'
  - '#qdrant-provisioning-trust'
date: '2026-10-05'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:874674938d069a748f58781f9ac1dbbbf1912ff1f3b0953cfc17b8a5a6b3589b'
related:
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
  - "[[2026-06-13-provisioning-setup-adr]]"
---

# `qdrant-provisioning-trust` audit: `managed qdrant binary provisioning and execution path review`

## Scope

How a host installation obtains, verifies, and executes the managed Qdrant server binary when `vaultspec-rag server start` runs on a machine that has never provisioned one, read against the verify-before-execute contract of `2026-06-12-qdrant-server-provisioning-adr` and the front door of `2026-06-13-provisioning-setup-adr`. Covered: `src/vaultspec_rag/qdrant_runtime/_constants.py`, `_provision.py`, `_resolve.py`, `_supervise.py`, the start path in `src/vaultspec_rag/cli/_service_start.py`, the daemon start in `src/vaultspec_rag/server/_lifespan.py`, and the heartbeat restart in `src/vaultspec_rag/server/_lifecycle.py`. Three probes ran: a PATH lookup probe on Windows, an install-state probe in an isolated status directory, and a comparison of the six committed archive digests against the upstream release API for tag `v1.19.0` (all six match). No download and no binary execution was performed.

## Findings

### path-tier-cwd-exec | high | a qdrant file in the working directory is executed instead of provisioning

The third resolution tier is `shutil.which("qdrant")` at `src/vaultspec_rag/qdrant_runtime/_resolve.py:824`. On stock Windows that lookup searches the current directory first and returned `.\qdrant.CMD` and `.\qdrant.EXE` in the probe. On a machine with no operator binary and no managed install the first two tiers are empty, so `_ensure_qdrant_binary` returns early at `src/vaultspec_rag/cli/_service_start.py:338` with no download and no console message. The daemon is spawned without a working directory at `src/vaultspec_rag/cli/_process.py:894`, resolves the same file, and the only signal is a warning in the service log at `src/vaultspec_rag/qdrant_runtime/_supervise.py:1352`. The lookup is confirmed; the execution step is traced by reading. A PATH binary is also assumed to be the pinned version for the store-format judgement at `src/vaultspec_rag/qdrant_runtime/_supervise.py:1368`.

### pre-exec-self-attested | high | the pre-execution check trusts a digest stored beside the binary and can be skipped

Only the archive digest is a code constant. The executable digest is read from `manifest.json` in the same directory at `src/vaultspec_rag/qdrant_runtime/_resolve.py:787` and compared at `src/vaultspec_rag/qdrant_runtime/_supervise.py:1328`. A manifest carrying only a `version` key resolves as `provisioned` with an empty digest, and the comparison branch is not taken, with no warning (confirmed by probe). The archive is hashed at `src/vaultspec_rag/qdrant_runtime/_provision.py:371` and then reopened by path for extraction at `src/vaultspec_rag/qdrant_runtime/_provision.py:306`, and whatever is extracted is recorded as trusted. The build toolchain already pins executable digests in `tools/binaries/bun_pins.py:27` and checks them with `verify_native_binary`; the qdrant path uses a second inline comparison.

### respawn-unverified | medium | restarts re-execute the binary without re-hashing

The heartbeat restart at `src/vaultspec_rag/server/_lifecycle.py:473` reaches `restart` at `src/vaultspec_rag/qdrant_runtime/_supervise.py:880`, and the quarantine retry loop at `src/vaultspec_rag/qdrant_runtime/_supervise.py:795` re-spawns as well. Neither re-verifies the executable.

### recovery-dead-end | medium | the documented recovery for a digest mismatch does nothing

A mismatch at start tells the operator to run `server qdrant install --upgrade` at `src/vaultspec_rag/qdrant_runtime/_supervise.py:1333`. `_existing_install_state` at `src/vaultspec_rag/qdrant_runtime/_provision.py:412` never hashes the binary, so a tampered binary with an intact manifest reports `unchanged` both with and without `--upgrade` (confirmed by probe). `src/vaultspec_rag/tests/test_qdrant_runtime.py:312` asserts that behaviour.

### install-not-atomic | medium | a failed or interrupted install destroys or strands an install

The generic failure handler unlinks the existing binary at `src/vaultspec_rag/qdrant_runtime/_provision.py:537` even when the failure was the download, so `--upgrade` over a working operator-registered install while offline removes it. Extraction writes in place at the final name; an interrupt mid-extract leaves a truncated binary with no manifest, which every later provision reports as a stale install that needs `--upgrade`.

### start-does-not-provision | medium | a default start on an unprovisioned host fails instead of provisioning

`--qdrant-auto-provision` defaults off at `src/vaultspec_rag/cli/_service_start.py:268`, so a plain `server start` exits with `qdrant_missing`. Models have no such gate: the daemon loads them online-capable unless the hub offline switch is set (`src/vaultspec_rag/config/_types.py:269`). The two fetch-and-go dependencies therefore behave differently on the same command. The client refusal sits in `_preflight_daemon_accelerator` at `src/vaultspec_rag/cli/_service_start.py:555`, which runs after the binary check at `src/vaultspec_rag/cli/_service_start.py:913`.

### duplicate-model-fetch | low | two implementations fetch model snapshots

`provision_models` at `src/vaultspec_rag/commands/_provision.py:413` and the `server warmup` loop at `src/vaultspec_rag/cli/_service_lifecycle.py:243` each probe the cache and call the hub download for the same repo list.

### download-hardening | low | staging, locking, deadline, and allowlist gaps

The `.partial` staging file is opened without the no-follow guard the extraction target has (`src/vaultspec_rag/qdrant_runtime/_provision.py:254`). The staging name is fixed and nothing serialises provisioning, so concurrent starts collide. The 120 second timeout is per socket operation with no overall deadline. `api.github.com` is allow-listed at `src/vaultspec_rag/qdrant_runtime/_constants.py:61` and never used. The release base URL and host set are code constants with no settings override. An unsupported platform raises `RuntimeError` from `provision` at `src/vaultspec_rag/qdrant_runtime/_provision.py:599`, which nothing in `src/vaultspec_rag/cli/_service_start.py` catches.

### stale-provisioning-prose | low | comments and a published phase say the daemon provisions

`src/vaultspec_rag/server/_lifespan.py:463` and the `_no_progress` docstring in `src/vaultspec_rag/qdrant_runtime/_provision.py:70` describe daemon-side provisioning; `start_supervised_from_config` only resolves and raises. The resolution docstring promises a version-skew warning for a PATH binary that does not exist.

## Recommendations

- For `path-tier-cwd-exec`: a follow-on ADR must decide whether an implicit PATH lookup remains a resolution tier at all once provisioning is automatic.
- For `pre-exec-self-attested`, `respawn-unverified`, and `recovery-dead-end`: a follow-on ADR must decide where the executable digest is anchored and at which points it is checked.
- For `start-does-not-provision`: a follow-on ADR must decide the consent model for the binary on `server start`, and where the client and host roles are gated relative to any download.
- For `install-not-atomic` and `download-hardening`: stage, verify, then replace; serialise provisioning; bound the download; route the source through settings. The override shape for the source is a decision for the same ADR.
- For `duplicate-model-fetch` and `stale-provisioning-prose`: collapse to one implementation and correct the prose in the change that touches each site.
