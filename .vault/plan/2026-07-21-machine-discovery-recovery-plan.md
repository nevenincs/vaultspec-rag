---
tags:
  - '#plan'
  - '#machine-discovery-recovery'
date: '2026-07-21'
modified: '2026-07-22'
tier: L3
related:
  - '[[2026-07-21-machine-discovery-recovery-adr]]'
  - '[[2026-07-21-machine-discovery-recovery-research]]'
  - '[[2026-07-21-machine-discovery-recovery-reference]]'
---

# `machine-discovery-recovery` plan

## Description

Restore machine discovery as an owner-authenticated, self-healing view of the OS-held
singleton. The plan first closes the test-isolation hole and establishes retained lock
ownership, then repairs heartbeat and shutdown ordering, introduces typed degraded
resolution, migrates canonical operator status, exposes bounded non-destructive reconcile,
and verifies the complete lifecycle with real locks and processes. B6 remains evidence-gated:
the plan adds the missing losing-daemon regression but authorizes no speculative production
change if current startup already satisfies it.

The machine-global daemon currently running on the host is outside the test scope. Every
execution step uses isolated status and Qdrant-storage roots, and no step restarts or mutates
the operator service.

## Steps

## Wave `W01` - owner authority and isolation

Establish fail-closed test isolation, retained singleton ownership, and self-healing publication before any client or adapter depends on the new discovery states.

### Phase `W01.P01` - singleton test isolation

Make both managed singleton paths unconditionally test-owned and prove ambient variables cannot redirect writers into operator state.

- [x] `W01.P01.S01` - Force status and Qdrant storage paths beneath one session-owned temporary root and reset cached configuration at every test boundary; `src/vaultspec_rag/tests/conftest.py`.
- [x] `W01.P01.S02` - Enforce the session-owned containment root before singleton writes and process control whenever pytest is active; `src/vaultspec_rag/`.
- [x] `W01.P01.S03` - Prove ambient and in-test path changes cannot redirect singleton writers into a test-owned trap outside the session root; `src/vaultspec_rag/tests/test_managed_singleton_isolation.py`.

### Phase `W01.P02` - owner lease and pointer primitives

Introduce retained ownership and atomic pointer mutation primitives before lifecycle writers are migrated.

- [x] `W01.P02.S04` - Define a retained machine-lock lease and owner-checked atomic pointer publish and delete primitives; `src/vaultspec_rag/_machine_lock.py`.
- [x] `W01.P02.S05` - Verify a real foreign lock holder blocks pointer publication and deletion while the retained owner succeeds; `src/vaultspec_rag/tests/integration/test_machine_singleton.py`.

### Phase `W01.P03` - heartbeat and shutdown convergence

Make daemon snapshots self-healing and order heartbeat quiescence, pointer cleanup, and lease release safely.

- [x] `W01.P03.S06` - Build heartbeat snapshots from daemon-owned state and repair both discovery views independently; `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `W01.P03.S07` - Thread the retained lease through startup and quiesce heartbeat before owner cleanup and lock release; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `W01.P03.S08` - Verify deleted records self-heal and shutdown cannot resurrect discovery after cleanup; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

### Phase `W01.P04` - losing daemon boundary proof

Reproduce the singleton race with real HTTP processes and authorize no production lifecycle change unless the boundary fails.

- [x] `W01.P04.S09` - Prove a losing real HTTP daemon exits nonzero before listener, Qdrant, pointer, watcher, or maintenance startup; `src/vaultspec_rag/tests/integration/test_machine_singleton.py`.

## Wave `W02` - typed resolution and canonical operability

Replace ambiguous optional-port discovery with one service-domain resolution and migrate operator and transport consumers after owner publication is trustworthy.

### Phase `W02.P05` - typed discovery resolution

Represent ready, absent, and each live-holder degradation with preserved identity and freshness evidence.

- [x] `W02.P05.S10` - Define typed machine resolution with holder and pointer identity, freshness, source, and reasoned degraded states; `src/vaultspec_rag/serviceclient/_discovery.py`.
- [x] `W02.P05.S11` - Export typed discovery without widening the torch-free service-client import surface; `src/vaultspec_rag/serviceclient/__init__.py`.
- [x] `W02.P05.S12` - Verify ready, absent, missing, invalid, stale, foreign-PID, and legacy fallback resolution against real locks; `src/vaultspec_rag/tests/test_machine_discovery_resolution.py`.

### Phase `W02.P06` - canonical status adapters

Move status derivation into the shared client domain and make CLI status and doctor render the same verdict.

- [x] `W02.P06.S13` - Define the canonical discovery status and health-composition model shared by operator adapters; `src/vaultspec_rag/serviceclient/_status.py`.
- [x] `W02.P06.S14` - Adapt server status rendering and exit semantics to ready, degraded, and absent discovery verdicts; `src/vaultspec_rag/cli/_status_render.py`.
- [x] `W02.P06.S15` - Adapt server doctor to the canonical discovery status without duplicating resolution logic; `src/vaultspec_rag/cli/_service_doctor.py`.
- [x] `W02.P06.S16` - Verify human and JSON status and doctor outcomes preserve typed discovery evidence; `src/vaultspec_rag/tests/test_cli_status.py`.

### Phase `W02.P07` - transport failure propagation

Carry degraded discovery reasons through service-dependent transport errors without fallback or guessed addresses.

- [x] `W02.P07.S17` - Propagate typed degraded discovery through service-dependent transport errors without compatibility fallback; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `W02.P07.S18` - Verify service clients fail fast with holder and pointer evidence for every degraded resolution; `src/vaultspec_rag/tests/test_http_admin_errors.py`.

## Wave `W03` - bounded reconcile and public contract

Expose non-destructive owner-driven reconciliation and update the consumer-facing discovery contract after typed status behavior is stable.

### Phase `W03.P08` - owner-driven reconcile

Poll boundedly for owner heartbeat convergence and expose an idempotent non-destructive operator command.

- [ ] `W03.P08.S19` - Implement bounded owner-driven reconcile over repeated typed resolution and identity-confirmed health; `src/vaultspec_rag/serviceclient/_status.py`.
- [ ] `W03.P08.S20` - Expose an idempotent non-destructive server reconcile command with structured outcomes; `src/vaultspec_rag/cli/_service_reconcile.py`.
- [ ] `W03.P08.S21` - Register the reconcile adapter without changing existing lifecycle command contracts; `src/vaultspec_rag/cli/__init__.py`.
- [ ] `W03.P08.S22` - Verify real-daemon recovery from deleted, stale, and foreign pointers without PID change or process termination; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

### Phase `W03.P09` - discovery contract documentation

Revise the consumer-facing discovery contract through the mandatory documentation pipeline after behavior is verified.

- [ ] `W03.P09.S23` - Revise the public discovery schema, ownership, degraded-state, and reconcile contract through vaultspec-documentation; `docs/service-discovery.md`.

## Wave `W04` - system verification and review

Prove the complete discovery lifecycle with real processes and finish with the mandatory architecture and safety review.

### Phase `W04.P10` - end-to-end regression suite

Exercise repair, mismatch, fallback, status, transport, reconcile, and loser behavior through production entry points.

- [ ] `W04.P10.S24` - Run the focused discovery, status, doctor, transport, lifecycle, and singleton regression suites; `src/vaultspec_rag/tests`.
- [ ] `W04.P10.S25` - Exercise isolated end-to-end start, corruption, heartbeat repair, reconcile, search resolution, and clean shutdown; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

### Phase `W04.P11` - architecture and safety audit

Review the completed implementation against the accepted ADR, lifecycle rules, and real-behavior test mandate.

- [ ] `W04.P11.S26` - Perform the mandatory code review for authority, shutdown ordering, adapter convergence, isolation, and test integrity; `.vault/audit/2026-07-21-machine-discovery-recovery-audit.md`.

## Parallelization

Waves execute in order because typed resolution depends on trusted publication and reconcile
depends on the canonical status model. Within W01, P01 can proceed before or alongside the
initial P02 implementation, but all real-process tests consume the completed isolation guard.
P02 and the B6 proof in P04 may proceed in parallel; P03 depends on P02. Within W02, P05 lands
before P06 and P07, while the CLI and transport adapter migrations may then proceed in
parallel. W03 documentation starts only after reconcile behavior and its integration test are
stable. W04 is strictly last.

The job-control and large-index plans do not share discovery implementation files and may run
in parallel after their own approval, subject to the shared dirty-merge coordination and GPU
test serialization.

## Verification

- Targeted plan checks report canonical L3 identifiers, contiguous Steps, and no placeholder,
  link, frontmatter, or markdown error.
- Tests prove both managed singleton paths are session-owned even when ambient variables are
  set or a test attempts to redirect them.
- A foreign real lock holder cannot publish or delete the machine pointer; the retained owner
  can do both atomically.
- Deleting or corrupting either discovery view under an isolated real daemon converges on the
  next heartbeat without restart, while shutdown cannot recreate cleaned records.
- Live-holder mismatch states render degraded with holder and pointer evidence, never stopped
  and never accepted through compatibility fallback.
- Reconcile is idempotent, bounded, non-destructive, and succeeds only after holder, pointer,
  freshness, token, address, and health agree.
- A losing real HTTP process exits nonzero before listener, Qdrant, pointer, watcher, or
  maintenance startup. A passing result closes B6 without product-code churn.
- The focused and end-to-end suites pass without fakes, mocks, patches, monkeypatches, skips,
  or expected failures.
- The public discovery document passes the vaultspec-documentation technical and editorial
  review gates.
- The mandatory code-review audit reports no unresolved authority, lifecycle, operability,
  isolation, or test-integrity finding.
