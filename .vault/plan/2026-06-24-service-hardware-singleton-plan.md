---
tags:
  - '#plan'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
tier: L3
related:
  - '[[2026-06-24-service-hardware-singleton-adr]]'
---








# `service-hardware-singleton` plan

## Wave `W01` - Failure legibility and detection primitives

Make Qdrant child failures visible (D5) and build the port-holder, storage-lock, and orphan detection primitives (D3). Foundation: nothing downstream can be verified or guarded without legible failures and reliable holder detection. Required by all later Waves.


### Phase `W01.P01` - Child-output capture and readiness diagnosis

Capture the Qdrant child's stdout/stderr to the log reliably and report a non-ready exit with its named cause instead of an opaque timeout.

- [ ] `W01.P01.S01` - Capture the qdrant child stdout and stderr to the log reliably across platforms; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [ ] `W01.P01.S02` - Report a non-ready child exit with the captured log tail and a named cause; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [ ] `W01.P01.S03` - Test that a non-ready child surfaces its cause instead of an opaque timeout; `src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py`.

### Phase `W01.P02` - Holder and orphan detection

Resolve who holds the Qdrant port and storage lock, and classify a managed orphan (our storage, dead owner).

- [ ] `W01.P02.S04` - Add a qdrant port-holder probe reporting whether a managed server is listening; `src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [ ] `W01.P02.S05` - Add a storage-lock probe distinguishing a live holder from a dead owner; `src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [ ] `W01.P02.S06` - Classify a managed qdrant orphan by expected storage and dead owner pid; `src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [ ] `W01.P02.S07` - Unit-test the holder and orphan detection primitives; `src/vaultspec_rag/tests/test_qdrant_detection.py`.

## Wave `W02` - Verified Qdrant attach

Attach to an already-running Qdrant instead of spawning a competitor (D2), gated on health, capability (version + storage path), and an ownership signal (D4). Depends on W01's detection + legibility; required by W04 adversarial attach tests.

### Phase `W02.P03` - Ownership identity signal

Record and validate a local-trust machine identity for the managed Qdrant so attach can confirm ownership, not just version.

- [ ] `W02.P03.S08` - Write a machine-local qdrant identity sidecar on bring-up (storage, version, owner token); `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [ ] `W02.P03.S09` - Validate the identity signal under local trust for safe attach; `src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [ ] `W02.P03.S10` - Unit-test identity write and validation; `src/vaultspec_rag/tests/test_qdrant_identity.py`.

### Phase `W02.P04` - Attach decision and wiring

Implement the health + capability + ownership attach gate and wire it into the supervised-start path so a running healthy Qdrant is reused, never re-spawned.

- [ ] `W02.P04.S11` - Implement the attach gate: health, version match, storage match, ownership; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [ ] `W02.P04.S12` - Make supervised start attach-or-spawn using the gate; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [ ] `W02.P04.S13` - Refuse fast without spawning when a holder fails the attach gate; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [ ] `W02.P04.S14` - Integration-test attach to a healthy managed qdrant with no second spawn; `src/vaultspec_rag/tests/integration/test_qdrant_attach.py`.
- [ ] `W02.P04.S15` - Integration-test refuse-fast on unhealthy, wrong-version, or foreign holder; `src/vaultspec_rag/tests/integration/test_qdrant_attach.py`.

## Wave `W03` - Machine-singleton service

Make the resident service one-per-machine (D1) via a crash-safe machine-scoped lock, and reap provably-dead managed orphans before spawn (D3 action). Depends on W01; complements W02.

### Phase `W03.P05` - Machine-scoped start guard

Add a crash-safe machine-scoped lock and make server start detect an existing healthy service machine-wide and refuse to spawn a second.

- [ ] `W03.P05.S16` - Add a crash-safe machine-scoped service lock under the managed dir; `src/vaultspec_rag/cli/_process.py`.
- [ ] `W03.P05.S17` - Make server start detect an existing healthy machine service and refuse with a pointer; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [ ] `W03.P05.S18` - Reclaim a stale machine lock held by a dead owner on start; `src/vaultspec_rag/cli/_process.py`.
- [ ] `W03.P05.S19` - Integration-test that a second start refuses and a stale lock is reclaimed; `src/vaultspec_rag/tests/integration/test_machine_singleton.py`.

### Phase `W03.P06` - Orphan reaping on start

Reap a provably-dead managed Qdrant orphan before spawning so a leaked prior child cannot block startup.

- [ ] `W03.P06.S20` - Reap a provably-dead managed qdrant orphan before spawning; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [ ] `W03.P06.S21` - Integration-test that a dead orphan is reaped and a live holder is never killed; `src/vaultspec_rag/tests/integration/test_qdrant_orphan_reap.py`.

## Wave `W04` - Adversarial verification and hardening

Prove the backend serves correctly under multi-user, multi-repo, adversarial conditions: concurrent multi-start races, orphan and corrupt-collection/unhealthy-Qdrant injection, and concurrent multi-repo search+index load. The acceptance gate; depends on all prior Waves.

### Phase `W04.P07` - Adversarial concurrency harness

Drive concurrent multi-start races, orphan/lock injection, unhealthy/corrupt-Qdrant injection, and multi-repo concurrent load against real service plumbing.

- [ ] `W04.P07.S22` - Adversarial: N concurrent starts yield exactly one service and one qdrant; `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py`.
- [ ] `W04.P07.S23` - Adversarial: an injected held port or storage lock yields fast-fail or reap, never a competitor; `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py`.
- [ ] `W04.P07.S24` - Adversarial: an unhealthy or corrupt qdrant holder is refused-attach with a named cause; `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py`.
- [ ] `W04.P07.S25` - Adversarial: concurrent multi-repo search and index load through one service holds under saturation; `src/vaultspec_rag/tests/integration/test_adversarial_multirepo.py`.

### Phase `W04.P08` - Acceptance and hardening audit

Run the full hardening gate and record the adversarial results in an audit.

- [ ] `W04.P08.S26` - Run the full hardening gate across unit, integration, and adversarial suites; `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py`.
- [ ] `W04.P08.S27` - Author the hardening audit summarizing the adversarial verification results; `.vault/audit/2026-06-24-service-hardware-singleton-hardening-audit.md`.

## Description

Harden the RAG backend so it serves correctly under multi-user, multi-repo, adversarial
conditions, implementing decisions D1-D5 of the service-hardware-singleton ADR. The driving
finding (sibling research): the managed Qdrant is a machine singleton (one port, one
single-writer storage) but the service architecture permits multiple instances that spawn
Qdrant blindly, so an orphaned Qdrant or a corrupt collection bricked the whole machine's RAG
behind an opaque 300s timeout.

The sequencing is legibility-first. Wave W01 makes failures visible (capture the child's
output and report a named cause) and builds the detection primitives (port-holder, storage
lock, orphan classification) - nothing downstream can be guarded or verified without these.
Wave W02 implements verified Qdrant attach: a running healthy Qdrant of the managed version,
serving the expected storage, with a valid ownership signal, is reused rather than re-spawned;
any holder that fails the gate yields a fast, named refusal instead of a doomed competing
child. Wave W03 makes the resident service one-per-machine via a crash-safe machine-scoped
lock and reaps provably-dead managed orphans before spawn. Wave W04 is the acceptance gate:
adversarial concurrency (N concurrent starts, orphan/lock injection, unhealthy/corrupt-Qdrant
injection) and concurrent multi-repo search+index load through one service's seats, all
against real service plumbing per the no-mock mandate.

The central safety property: attach is gated on health + capability + ownership, because
attaching to an unhealthy, wrong-version, wrong-storage, or unowned server is worse than
spawning; and a second resident is refused, because one GPU and one single-writer Qdrant
cannot be co-owned.

## Steps







## Parallelization

The four Waves are strictly ordered: W01 (legibility + detection) is the foundation every
later Wave builds on; W02 (attach) and W03 (machine singleton) both depend on W01 and can be
developed in parallel, but W04 (adversarial verification) depends on both being landed. Within
W01, the capture Phase P01 and the detection Phase P02 are independent. Within W02, the
ownership-signal Phase P03 precedes the attach-gate Phase P04 (the gate validates the signal).
Within W03, the machine-lock Phase P05 and the orphan-reap Phase P06 are independent. Within
W04, the adversarial harness Phase P07 precedes the acceptance Phase P08.

## Verification

The plan is complete when every Step is closed and all of the following hold:

- A non-ready Qdrant child reports a named cause (panic / bind / lock) with its log tail; no
  failure presents as an opaque timeout.
- Starting a service when a healthy managed Qdrant is already serving ATTACHES (no second
  child spawns), verified by health + matching version + matching storage + a valid ownership
  signal; a holder failing any gate yields a fast, named refusal rather than a competing child.
- A second `server start` on the same machine (any port / status dir) is refused with a pointer
  to the running instance; a stale machine lock left by a dead owner is reclaimed.
- A provably-dead managed Qdrant orphan is reaped before spawn; a live holder is never killed.
- Adversarial gate: N concurrent starts converge to exactly one service and one Qdrant;
  injected held ports/locks and unhealthy/corrupt Qdrant holders never produce a competitor or
  a whole-machine outage; concurrent multi-repo search+index load through one service's seats
  holds under saturation.
- The full unit + integration + adversarial suites pass on the real GPU + real Qdrant with
  zero lint or type violations (no mocks, stubs, or skips), and the hardening audit records the
  adversarial results.
