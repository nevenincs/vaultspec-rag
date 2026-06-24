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

- Land `W04.P09.S28`-`S33` as the post-acceptance follow-ups; none block the core guarantees,
  which are verified.
- The plan's S27 scope names `-hardening-audit.md`; the CLI scaffolded the canonical
  `2026-06-24-service-hardware-singleton-audit.md`. Treat this file as the feature's audit.

### Code-review outcome (two vaultspec-code-reviewer passes, resolved)

Two independent review passes ran. All HIGH/MEDIUM blockers are fixed and re-verified
(42-test gate green). The lock went through three designs across the reviews, landing on an
OS advisory lock as the correct primitive.

**First pass** returned one HIGH and three MEDIUM:

- **HIGH-1 (superseded by the second-pass rewrite): empty-lock crash deadlock.** The
  `O_EXCL`-create-then-write lock could be left empty by a crash in the write window, which the
  prior mid-write-race fix treated as permanently held - a machine-wide deadlock. First fixed
  by claiming via `os.link` of a pid-bearing temp file; the second pass then found that fix
  still racy (below) and it was replaced by the OS-lock design.
- **MEDIUM-1 (fixed): reap of a recycled pid.** The reaper killed `qdrant_pid` without
  confirming it was still a qdrant process; a recycled pid could be an unrelated process.
  Added `pid_image_is_qdrant` and gated the reap on it (refuse rather than kill a non-qdrant
  pid). Regression test added.
- **MEDIUM-2 (fixed): version gate bypass on empty version.** `verify_attachable` skipped the
  version check when the probe version was empty; now an unreadable version is a gate failure.
  Regression test added.
- **MEDIUM-3 (tracked `W04.P09.S32`): owner-pid-reuse misclassification.** A recycled owner
  pid can read as a live `managed_running` owner; data safety holds (health/version/storage
  gates), but the ownership proof should add a start-time/nonce.
- **LOW-1 (tracked `W04.P09.S33`): reap-to-spawn bind race.** A short post-reap settle before
  spawn would make it deterministic; today it degrades to a named failure. (Separately, the
  second pass's note about a timing-fragile 2s sleep in the race test was resolved by the
  race-worker rewrite below - the OS lock is held for the worker's lifetime, no sleep needed.)

**Second pass** verified the first three fixes and found a NEW HIGH plus a MEDIUM, both now
fixed:

- **HIGH (NEW, fixed): two-winner reclaim race.** The `os.link` *fresh-claim* was exclusive,
  but the stale-lock *reclaim* path (unlink-then-retry, the orphan-recovery case) still let one
  contender unlink another's freshly-won lock - a real double-acquire of the machine gate.
  **Resolved by replacing the whole file-based create/reclaim scheme with an OS advisory lock**
  (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows) held for the holder's process lifetime.
  The OS guarantees exclusion with no create/reclaim window and releases the lock automatically
  on process death - so there is no stale-file reclaim at all, no empty-lock deadlock, and no
  two-winner race. The Windows lock is taken at a high byte offset so the recorded pid (offset
  0) stays readable for the refusal message. New regression tests: a dead-holder concurrent
  race (N starts → one winner over the orphan path), a real lock-holding subprocess as the
  foreign holder, and release idempotency.
- **MEDIUM (NEW, fixed): uncaught `os.link` `EXDEV`/non-NTFS error.** Moot under the OS-lock
  rewrite (no `os.link`); `acquire` now opens the file and locks it, with no cross-device path.

- **LOW-2:** resolved by the rewrite (no empty-lock state). **LOW-3** (ADR identifiers in
  comments) is consistent with the pervasive existing convention in this codebase; left as-is.

**Third pass** (on the OS-lock rewrite specifically) verified the lock semantics empirically on
a win32 host (past-EOF lock, foreign-holder block, dead-holder auto-release, fd lifetime, test
hygiene all confirmed clean) and found one more HIGH:

- **HIGH (NEW, fixed): POSIX unlink-race in `release_machine_lock`.** Release unlocked, closed
  the fd, then `unlink`-ed the file - three non-atomic steps. On POSIX a contender acquiring in
  the unlock->unlink window had its freshly-locked file deleted out from under it, and the next
  acquire created a fresh inode and locked it uncontended: two live holders (Windows was benign
  - unlink-while-open raises a sharing violation). The common `server stop`->`server start`
  overlap triggers it. Fixed by NOT unlinking on release at all - the file's existence is not
  the authority (the OS lock is), a lingering file is harmless, and the next acquirer overwrites
  the stale pid. Dependent test assertion updated (release -> re-acquirable, not file-absent).

The three-reviewer arc is itself the lesson: a file-`O_EXCL`/`os.link` lock with any manual
file manipulation (create, reclaim, OR unlink) is inherently racy; an OS advisory lock with NO
unlink is the correct primitive for a machine singleton. This generalizes the `W04.P09.S31`
codify candidate.

## Codification candidates

- **Source:** the `W04.P09.S31` finding (writers target the real machine path without storage
  isolation). **Rule slug:** `managed-singleton-paths-isolate-storage-dir-in-tests`. **Rule:**
  Any test or caller that exercises `write_qdrant_identity` or `acquire_machine_lock` must set
  `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to a temp path (the machine-global identity/lock paths
  derive from it), or it will read and write the real machine-global managed directory.

  This candidate has held across exactly one execution cycle (the leak, then the `_service_env`
  fix); per the codify rule it qualifies for promotion after the follow-up `S31` confirms it
  across the lifecycle-test fix, not before.


