---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S12'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# run the full quality gates on the changed surface and fold measured numbers into the ADR consequences

## Scope

- `repository quality gates`
- `.vault/adr/2026-07-24-index-throughput-adr.md`

## Description

- Run the repository's gates over the surface this campaign changed: the
  store, the streaming module, the vault split, the concurrency limiters, and
  the job manager, models and dispatch.
- Run the suites that own the changed behaviour: slice-writer overlap, vault
  split parallelism, admission display, encode hygiene, the jobs unit suite,
  and the ingest-barrier integration suite.
- Rewrite the decision record's consequences so every claim carries its
  measurement status, replacing the projected numbers with the measured ones
  and stating plainly what is still unmeasured.

## Outcome

Gates green on the changed surface:

- ruff over `src`: no finding in any file this campaign touched.
- ty over the ten changed modules: all checks passed.
- basedpyright (the strict CI gate) over the store, streaming, vault split,
  concurrency, job manager, job models and job dispatch: 0 errors, 0 warnings,
  0 notes.
- complexity gate: PASS (cyclomatic and nesting-depth).
- citation gate: clean, no development-record citations and no workstation
  path leaks.
- markdown gates over this feature's documents: mdformat and pymarkdown clean.
- vault check over the feature: all checks pass.
- module-length gate: report-only by configuration; no module in this
  campaign's surface changed category.
- suites: 28 passed (slice-writer overlap, vault split parallelism, admission
  display, encode hygiene), 6 passed (ingest barrier, including the
  silent-drop injection and the writer composition case), 69 passed (jobs
  unit).

Decision record updated: the consequences section no longer projects. Each
bullet is labelled MEASURED or NOT MEASURED, the admission-gate numbers
(exclusivity across 31,878 window pairs, in-run lock wait at p50 0.000 s,
inflation 1.029x median against a pre-gate 2.3-5.0x, sub-second uncontended
admission cost) and the ingest numbers (arm medians 80.1 s against 78.1 s,
barrier 0.060-0.242 s) replace the projections, and the two untaken items -
the flush-cadence flip and the gRPC transport switch - state their blocking
condition.

## Notes

- Two failures in the tree are not from this campaign and were left alone:
  ruff reports an undefined name in `src/vaultspec_rag/storage_ops.py` from
  another agent's in-flight reclaim work, and
  `src/vaultspec_rag/tests/integration/test_jobs_registry.py` fails to import
  because a concurrent refactor removed the server jobs module the test still
  names. Both belong to their owners.
- The full repository suite was not run: the tree was being edited by nine
  agents throughout, so a whole-suite result would have measured their
  in-flight state rather than this surface. The gate scope here is this
  campaign's files and the suites that own its behaviour.
