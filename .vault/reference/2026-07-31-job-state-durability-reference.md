---
tags:
  - '#reference'
  - '#job-state-durability'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:1ffe09541784fa41e8a4df8149eadc236134c56dbf68e9be294e8980a521d1dd'
related:
  - "[[2026-07-31-job-state-durability-adr]]"
---

# `job-state-durability` reference: `job-state persistence implementation grounding`

Grounding for the job-state durability decisions, drawn from the shipped incident and
the completed implementation itself. Sources: the incident report (a daemon rendered
permanently unstartable by its own state file), the implementation across the job
persistence stack, and the contract and recovery test suites.

## Summary

**The incident.** The canonical job-state file held JSON `null` where a float was
required, in 19 of 20 records. Restore is all-or-nothing and its failure was a fatal
startup abort, so every start died with a persistence error naming a field no running
process had written. The corrupt records were traced by their recorded runtime prefix
to an intermediate development build, not to the released writer, but the fragility was
shipped: a file the daemon writes itself could brick it with no operator escape hatch.

**The persistence stack.** The versioned codec and atomic storage live in
`src/vaultspec_rag/job_persistence.py`: the schema header validation and version range
(`src/vaultspec_rag/job_persistence.py:369`, floor at
`src/vaultspec_rag/job_persistence.py:87`), the newer-build error type
(`src/vaultspec_rag/job_persistence.py:135`), the write path on the shared atomic
publisher (`src/vaultspec_rag/job_persistence.py:177`), orphaned-temporary reclamation
(`src/vaultspec_rag/job_persistence.py:213`), and the persisted-lifecycle map
(`src/vaultspec_rag/job_persistence.py:526`). The manager-side restore dispositions
live in `src/vaultspec_rag/job_manager/_persistence.py`: the error-classified load
(`src/vaultspec_rag/job_manager/_persistence.py:230`), quarantine
(`src/vaultspec_rag/job_manager/_persistence.py:270`), newer-build preservation
(`src/vaultspec_rag/job_manager/_persistence.py:315`), the shared set-aside move
(`src/vaultspec_rag/job_manager/_persistence.py:369`), the persistence funnel every
lifecycle transition writes through (`src/vaultspec_rag/job_manager/_persistence.py:524`),
per-record stamp flooring (`src/vaultspec_rag/job_manager/_persistence.py:638`), and
collision-stepping preserved names
(`src/vaultspec_rag/job_manager/_persistence.py:713`).

**Construction-time validation.** The persisted models in
`src/vaultspec_rag/job_models.py` validate in `__post_init__`: timestamps
(`src/vaultspec_rag/job_models.py:393`), process resource readings
(`src/vaultspec_rag/job_models.py:472`), the snapshot's scalar fields and telemetry
blocks (`src/vaultspec_rag/job_models.py:576`), with the JSON-native telemetry walk at
`src/vaultspec_rag/job_models.py:259`. The idempotency binding validates its flag at
`src/vaultspec_rag/job_persistence.py:108` against the same requirement string its
reader uses (`src/vaultspec_rag/job_persistence.py:96`). Progress publication
constructs the canonical record instead of mirroring its rules
(`src/vaultspec_rag/job_manager/_progress.py:434`). Capacity handling on restore is at
`src/vaultspec_rag/job_manager/_persistence.py:192` with the replay-binding floor at
`src/vaultspec_rag/job_manager/_records.py:378`.

**The defect matrix.** The audit driving the work compared every reader constraint
against whether a writer could violate it. Producer gaps found and closed: the scalar
resource fields, the idempotency flag, telemetry value spaces, and wall-clock
monotonicity under a backwards step. One loader error found and corrected: the
persisted-lifecycle map refused the paused-observed/running-desired pair that quiesce
parking deliberately writes and the resume pass selects on. One whole-file hazard
found: strict version equality would have routed every intact file into the corrupt
path on the first version bump.

**Verification.** The contract suite (`src/vaultspec_rag/tests/test_job_contracts.py`)
and the recovery integration suite
(`src/vaultspec_rag/tests/integration/test_jobs_registry_recovery.py`) drive real
lifecycle sequences through the manager and back through the real loader, cover every
restore disposition including the quarantine, newer-build, unreadable, and
failed-move branches, and sweep quiesce-parked work through the persisted round trip;
155 tests across the two suites pass on this branch.
