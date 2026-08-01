---
tags:
  - '#audit'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:2fbc3cfe4a603c61d286e2ada948d398c24ead9ae3489807153667919977c90a'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` audit: `W01.P01.S03 managed singleton isolation regressions`

## Scope

Independent review of the current `W01.P01.S03` regression file against the accepted
machine-discovery isolation decision, its plan and research/reference evidence, the
managed-singleton isolation rule, and the committed `W01.P01.S02` containment boundaries.
The review covered hostile ambient configuration before import, mutable in-test
configuration, process-local root pinning, exec-child adoption, independent status and
storage anchors, test-owned traps outside the session root, real writer/deleter/process
effects, deterministic cleanup, Windows/POSIX portability, test integrity, and direct
production imports. The focused test file passed all six collected cases on Windows and
BasedPyright reported no diagnostics.

## Findings

### guarded-seam-coverage | medium | Two committed containment boundaries lack regression proof

The test reaches the status-directory and write-lock path through
`_merge_service_status`, all three machine-lock operations, Qdrant identity and machine
pointer publication, both discovery deletions, service spawn and termination, orphan
reaping, and supervised Qdrant spawn. It never imports or invokes
`server._lifecycle._resolve_log_path`, so the daemon-side managed log-directory writer is
not proved to reject an escaped status anchor. More importantly, it never exercises
`QdrantSupervisor.stop` against a live owned process, so the distinct supervised-Qdrant
termination boundary is not covered by the sentinel-survival assertions for
`_terminate_pid` and `reap_qdrant_orphan`. A missing or displaced guard at either seam
would leave all six tests green. Because S03 is the executable closure proof for every
S02 writer/process boundary, this is an incomplete acceptance artifact.

### lint-gate | low | The new regression file fails the repository Ruff gate

`ruff format --check` and BasedPyright pass, but `ruff check` reports `SIM117` at the
independent-anchor regression because nested context managers can be combined. The
focused behavioral suite still passes six of six; this is a quality-gate failure rather
than a behavioral failure.

### guarded-seam-coverage-resolution | resolved | Both missing production boundaries now have real proof

The follow-up imports and invokes `_resolve_log_path` while the configured status anchor
escapes containment and proves it raises before creating the directory. It also starts a
manifest-backed provisioned Qdrant through `start_supervised_from_config` on isolated
storage and adjacent test ports, records the real child PID, redirects the configured
anchors, and proves `QdrantSupervisor.stop` raises before signalling while that exact PID
remains alive. After restoring contained configuration, the same production supervisor
stops the child and bounded cleanup removes its test-owned identity.

### lint-gate-resolution | resolved | The focused quality gates are clean

The nested contexts were combined. Ruff format and lint now pass, BasedPyright reports
zero diagnostics, and the expanded focused suite passes all seven real-behavior tests.

## Recommendations

Status: **REVISION REQUIRED**. Do not close `W01.P01.S03` while the medium finding remains.

Add direct imported-production coverage for `_resolve_log_path` with an escaped status
anchor and prove that no directory is created. Add a real live-process survival case for
`QdrantSupervisor.stop` that reaches its production-owned-child branch, rejects before a
signal, and then performs bounded deterministic cleanup after restoring the contained
configuration. Do not use a fake process, mock, patch, monkeypatch, skip, or expected
failure to make that branch reachable. Combine the nested contexts, rerun the focused
suite on the current file, and require Ruff format/check plus BasedPyright to pass before
requesting re-review.

## Re-review verdict

Status: **PASS after remediation**. The original medium and low findings are resolved,
with no remaining critical, high, medium, or low finding. The final tests directly import
production code, use real files, OS locks, an exec child, a sentinel process, and a verified
real Qdrant process. They contain no fake, mock, stub, patch, monkeypatch, skip, or expected
failure and do not mirror production policy.
