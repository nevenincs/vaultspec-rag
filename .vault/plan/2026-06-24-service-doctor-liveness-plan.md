---
tags:
  - '#plan'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
tier: L3
related:
  - '[[2026-06-24-service-doctor-liveness-adr]]'
---

# `service-doctor-liveness` plan

## Wave `W01` - Doctor live-service truth

Make server doctor consult the live-service truth that already exists on the status path so a dead daemon is never reported ready, while keeping the pre-runtime dependency axis intact. Self-contained; required before the flapping work only for shared test scaffolding.

### Phase `W01.P01` - Live-service axis in doctor

Add a live-service axis to doctor that reads the discovery file and probes health/port and reports a dead daemon honestly.

- [x] `W01.P01.S01` - Add a live-service axis to server doctor that reads the discovery file and probes health and port, reusing the status-path liveness truth; `src/vaultspec_rag/cli/_service_doctor.py`.
- [x] `W01.P01.S02` - Report ready:false or an explicit degraded/needs-restart status when the daemon is dead, keeping the installed-dependency axis present and labelled so the two are never conflated; `src/vaultspec_rag/cli/_service_doctor.py`.
- [x] `W01.P01.S03` - Reflect the real live qdrant runtime state in the doctor output rather than the binary-on-disk default that reads ready when no supervisor exists in-process; `src/vaultspec_rag/cli/_service_doctor.py`.

### Phase `W01.P02` - Doctor liveness regression

Prove doctor reports a not-ready/degraded live status with no daemon running while still reporting dependency readiness.

- [x] `W01.P02.S04` - Add a no-mock test asserting doctor reports a not-ready or degraded live status with no daemon running while still reporting dependency readiness truthfully; `src/vaultspec_rag/tests/integration/test_service_doctor_liveness.py`.

## Wave `W02` - Daemon flapping diagnosis and remediation

Confirm which flapping causes fire on this host, then remediate only the confirmed causes, coordinating the machine-singleton overlaps with that campaign. Depends on W01 only for shared lifecycle test helpers.

### Phase `W02.P03` - Flapping diagnosis

Instrument and reproduce the candidate flapping causes on this host to confirm which fire before any remediation.

- [x] `W02.P03.S05` - Instrument and reproduce the spawn-without-breakaway fallback to confirm whether the daemon survives the launching shell exit on this host; `src/vaultspec_rag/cli/_process.py`.
- [x] `W02.P03.S06` - Instrument and reproduce the identity-miss discovery-file unlink to confirm whether a concurrent status or start can delete a live daemon's discovery file; `src/vaultspec_rag/cli/_service_lifecycle.py`.

### Phase `W02.P04` - Flapping remediation

Remediate only the confirmed causes: daemon survival independent of the launching shell, and no discovery-file unlink on ambiguous identity.

- [x] `W02.P04.S07` - Make daemon survival independent of the launching shell: on a breakaway denial, detach so the daemon outlives the parent or fail loudly instead of the silent doomed fallback; `src/vaultspec_rag/cli/_process.py`.
- [x] `W02.P04.S08` - Unlink the discovery file only when the holder is confirmed dead, never on an ambiguous identity result, so a transient health or PID miss cannot delete a live service's file; `src/vaultspec_rag/cli/_service_lifecycle.py`.

### Phase `W02.P05` - Flapping regression

Prove the daemon survives a parent-shell exit and a concurrent command does not unlink a live daemon's discovery file, no mocks.

- [x] `W02.P05.S09` - Add a no-mock test that a daemon survives a simulated parent-shell exit on this platform; `src/vaultspec_rag/tests/integration/test_daemon_survives_shell_exit.py`.
- [x] `W02.P05.S10` - Add a no-mock test that a concurrent lifecycle command does not unlink a live daemon's discovery file on a transient identity miss; `src/vaultspec_rag/tests/integration/test_daemon_survives_shell_exit.py`.

## Description

Address the residual half of issue #204 that the machine-singleton campaign does not cover:
`server doctor` reporting a dead daemon as ready, and the daemon flapping. Wave W01 makes
doctor tell the truth - it currently never probes the live daemon and computes readiness from
installed dependencies and an on-disk binary in the CLI's own process, so a dead service reads
`ready: true`. W01 adds a distinct live-service axis (discovery file + health/port probe,
reusing the status-path truth) and keeps the dependency axis labelled and separate. Wave W02
attacks the flapping, deliberately staged: P03 confirms which of the research's candidate
causes actually fire on this host (the shell-scoped Job-Object daemon death; the
identity-miss discovery-file unlink) before P04 remediates only the confirmed ones, and P05
proves it with no-mock tests. The machine-lock-versus-status-dir and pre-yield-unlink causes
overlap the singleton campaign and are coordinated with its owners rather than re-fixed here.
Grounded in the ADR and its research; planning artifact only, ADR pending user sign-off.

## Steps

## Parallelization

The two Waves are largely independent and could proceed in parallel: W01 (doctor) touches the
doctor CLI surface and W02 (flapping) touches spawn and lifecycle, with no hard code overlap;
the only shared dependency is integration test scaffolding for standing up a real daemon, so
W01 landing first gives W02 a reusable harness. Within W02 the ordering is strict and
deliberate: P03 (diagnosis) gates P04 (remediation) - a remediation step is applied only for a
cause P03 confirms fires on this host - and P05 (tests) follows P04. Within W01, the three P01
steps are edits to one surface and are developed together; P02 follows. The
machine-lock-versus-status-dir and pre-yield-unlink causes are explicitly out of this plan's
remediation scope and are coordinated with the machine-singleton campaign.

## Verification

The plan is complete when every Step is closed and all of the following hold:

- `server doctor` reports a not-ready or explicit degraded/needs-restart live status when no
  daemon is running, while still reporting installed-dependency readiness on a separate,
  labelled axis; the qdrant block reflects real live state, not the binary-on-disk default.
- The flapping diagnosis records, in the execution trail, which candidate causes fire on this
  host; each remediation maps to a confirmed cause (no speculative changes).
- A daemon survives a simulated parent-shell exit on this platform (the confirmed dominant
  cause is fixed), proven by a no-mock test.
- A concurrent lifecycle command does not unlink a live daemon's discovery file on a transient
  identity miss, proven by a no-mock test.
- The full unit + integration suites stay green on the real host with no mocks, stubs, or
  skips; `ruff` and the type checker report zero violations; no machine-singleton guarantee is
  regressed.
