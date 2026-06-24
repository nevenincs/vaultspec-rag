---
tags:
  - '#audit'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---



# `service-hardware-singleton` audit: `hardening`

## Scope

The acceptance audit for the service-hardware-singleton hardening (ADR decisions D1-D5,
plan waves W01-W04). It records whether the backend now serves correctly under multi-user,
multi-repo, adversarial conditions, and tracks every issue surfaced during execution. The
audited surface is the Qdrant supervisor and runtime resolution, the machine-scoped service
lock, the CLI `server start`/`stop` lifecycle, and the daemon lifespan, plus their tests.

## Findings

### Verified (the central guarantees hold)

- **Legibility (D5).** A non-ready Qdrant child reports a named cause with its captured
  output tail instead of an opaque 300s timeout. The supervisor drains the child's combined
  output through a thread into the log and a bounded ring. Verified by the supervise
  diagnostics test.
- **Verified attach (D2, P1).** A running, healthy, owned, capable managed Qdrant is reused
  (attach mode), never re-spawned onto its single-writer storage; a holder failing the
  health/version/storage/ownership gate yields a fast, named refusal. Verified end to end
  against a real HTTP stand-in (attach / refuse-foreign / refuse-version-mismatch).
- **Orphan reaping (P2).** A provably-dead managed orphan (owner dead, child still holding
  the port) is reaped and a fresh child spawned; a live holder is never reaped (enforced at
  the decision layer). Verified by reaping a real spawned process.
- **Machine singleton (D1, P3).** One resident service per machine via a crash-safe lock
  co-located with the shared storage (machine-global across status-dir overrides). Verified
  by a REAL 8-process concurrent race converging to exactly one winner, plus stale-reclaim
  and live-foreign-holder fast-fail.
- **Adversarial gate (W04).** N concurrent starts -> one winner; injected held port/lock ->
  fast-fail or reap, never a competitor; unhealthy/corrupt holder -> refuse with a named
  cause; concurrent multi-repo search+index load through one service holds under saturation
  on the real GPU. Full hardening gate: 36 tests pass, no mocks/skips, zero lint/type
  violations.

### Issues surfaced during execution (all tracked in the plan)

- **HIGH (fixed mid-execution): machine-lock concurrent-create race.** The first lock
  implementation let a loser that read the winner's still-empty lock file reclaim it,
  producing two winners. Hardened to treat an empty/holder-0 file as held and only reclaim a
  nonzero-dead or own-pid holder. Surfaced and closed by the S22 multi-process test; no
  residual.
- **MEDIUM (tracked `W04.P09.S28`): lifespan lock release on pre-yield startup failure.** The
  daemon acquires the machine lock before `yield`; a startup failure before `yield` skips the
  release, leaving a stale lock that the next start reclaims (dead pid). Self-heals via the
  crash-safe path, but an immediate release is cleaner.
- **MEDIUM (tracked `W04.P09.S29`): service-lifecycle integration tests do not exercise the
  live daemon in this environment.** Under the isolated test `STATUS_DIR` no Qdrant binary is
  provisioned, so server-mode daemon tests fast-fail on the pre-existing binary guard before
  any daemon spawns. Root-caused as environmental and independent of the hardening changes
  (binary resolution is untouched; the failure precedes the lock acquire).
- **LOW (tracked `W04.P09.S30`): `server stop` lacks `--port`.** A service on a non-default
  port cannot be stopped by the verb (it errors `No such option '--port'`), compounding the
  research-F7 status-dir discovery divergence. Observed while restoring the environment.
- **LOW (tracked `W04.P09.S31`): identity / machine-lock writers target the real machine path
  unless `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` is isolated.** An early test iteration (using
  `config_override`, which does not reach `qdrant_storage_dir`) leaked an identity sidecar to
  the real managed dir; cleaned, and `_service_env` now isolates the storage dir. A codify
  candidate.

## Recommendations

- Land `W04.P09.S28`-`S31` as the post-acceptance follow-ups; none block the core guarantees,
  which are verified.
- Run `vaultspec-code-reviewer` over the W01-W04 diff before merge (mandatory per the execute
  skill), resolving any CRITICAL/HIGH before proceeding.
- The plan's S27 scope names `-hardening-audit.md`; the CLI scaffolded the canonical
  `2026-06-24-service-hardware-singleton-audit.md`. Treat this file as the feature's audit.

## Codification candidates

- **Source:** the `W04.P09.S31` finding (writers target the real machine path without storage
  isolation). **Rule slug:** `managed-singleton-paths-isolate-storage-dir-in-tests`. **Rule:**
  Any test or caller that exercises `write_qdrant_identity` or `acquire_machine_lock` must set
  `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to a temp path (the machine-global identity/lock paths
  derive from it), or it will read and write the real machine-global managed directory.

  This candidate has held across exactly one execution cycle (the leak, then the `_service_env`
  fix); per the codify rule it qualifies for promotion after the follow-up `S31` confirms it
  across the lifecycle-test fix, not before.


