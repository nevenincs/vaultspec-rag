---
tags:
  - '#plan'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_hash: 'sha256:9543381fec48450b72204c02147b6f30bfd3069b21d49dea3ded2ab3a02cba50'
tier: L3
related:
  - '[[2026-06-01-module-split-adr]]'
  - '[[2026-07-27-maintainability-remediation-research]]'
  - '[[2026-07-27-maintainability-remediation-radon-module-ownership-reference]]'
---

# `maintainability-remediation` plan

Remove the Radon MI floor from the ten reported modules through direct-owner decomposition, preserving live service behaviour and real integration coverage.

## Description

The amended module-split decision governs the direct-owner migration. Wave W01 establishes safe shared-worktree boundaries and moves the clean job-manager seam. Wave W02 handles the CLI job and durable ledger seams once their concurrent work is reconciled. Wave W03 splits the independent real integration scenarios and verifies that no reported module remains at the maintainability floor.

## Steps

Retained-plan evidence: the milestone and wave sections in this document are the step inventory; this canonical section preserves that inventory without duplicating it.

## Wave `W01` - protect shared work and establish direct owner seams

Reconcile the active shared-worktree changes before moving clean production responsibilities into concrete owners; later waves depend on the resulting import boundaries.

### Phase `W01.P01` - reconcile active overlapping changes

Preserve the live ledger and registry refactors while recording their owners and safe handoff boundaries.

- [x] `W01.P01.S01` - Reconcile the active direct-owner refactor before changing the service-job seam; `src/vaultspec_rag/cli/_service_jobs.py`.
- [x] `W01.P01.S02` - Reconcile the active commit-unit validation extraction before splitting ledger ownership; `src/vaultspec_rag/indexer/_run_ledger.py`.
- [x] `W01.P01.S03` - Reconcile the active snapshot assertion extraction before splitting registry scenarios; `src/vaultspec_rag/tests/integration/test_jobs_registry.py`.

### Phase `W01.P02` - split clean production responsibilities

Move the clean production modules into direct, single-owner seams and migrate their consumers without compatibility facades.

- [x] `W01.P02.S04` - Move job-manager value and execution responsibilities into concrete owners and migrate consumers; `src/vaultspec_rag/job_manager.py`.

## Wave `W02` - decompose durable index and CLI job seams

After the shared handoffs, divide the ledger and service-job adapters by their durable responsibility boundaries before integration scenarios move.

### Phase `W02.P03` - separate service-job presentation and control adapters

Keep command registration thin while concrete presentation, query, watch, and control owners preserve the existing service contract.

- [x] `W02.P03.S05` - Split presentation, query, watch, and control adapters into direct CLI owners; `src/vaultspec_rag/cli/_service_jobs.py`.

### Phase `W02.P04` - separate durable ledger ownership

Divide ledger models, generation lifecycle, commit evidence, file-state queries, and SQLite persistence without duplicating invariants.

- [x] `W02.P04.S06` - Split ledger models, lifecycle, evidence, query, and persistence ownership with direct importer migration; `src/vaultspec_rag/indexer/_run_ledger.py`.

## Wave `W03` - separate integration scenarios

Split each floor-score integration module by independent real-service behavior while retaining real process, transport, and storage coverage.

### Phase `W03.P05` - split index and installation scenarios

Separate index-control and installation behavior domains without replacing real service coverage.

- [x] `W03.P05.S07` - Split independent index job-control scenarios and retain real service assertions; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.
- [x] `W03.P05.S08` - Split installation topology, failure, lifecycle, and reporting scenarios; `src/vaultspec_rag/tests/integration/test_install.py`.

### Phase `W03.P06` - split job and lifecycle scenarios

Separate registry, job-control, service-job, and lifecycle behaviors into focused real integration modules.

- [x] `W03.P06.S09` - Split registry basics, durable recovery, and route-to-recorded-job scenarios; `src/vaultspec_rag/tests/integration/test_jobs_registry.py`.
- [x] `W03.P06.S10` - Split pause, cancellation, restart, watcher, and exact-ID control scenarios; `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`.
- [x] `W03.P06.S11` - Split service-job collection, CLI, HTTP control, and resilience scenarios; `src/vaultspec_rag/tests/integration/test_service_jobs.py`.
- [x] `W03.P06.S12` - Split startup, shutdown, discovery, and orphan-reaping lifecycle scenarios; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

### Phase `W03.P07` - split search diagnostics and prove the floor is removed

Separate matching-rebuild, transport, and diagnostics behavior, then prove the report and import graph satisfy the amended decision.

- [x] `W03.P07.S13` - Split matching-rebuild, HTTP, MCP, and timeout diagnostics scenarios; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- [x] `W03.P07.S14` - Strengthen direct-owner import coverage for moved production seams; `src/vaultspec_rag/tests/test_no_reexports.py`.
- [x] `W03.P07.S15` - Verify the maintainability floor and all focused real-behavior regressions; `tools/health_report.py`.

## Wave `W04` - eliminate duplicated declarations and gate what a split can regress

The module-size work surfaced a class of defect the gates could not see: a declaration duplicated across a new seam, a decorator orphaned by a line-range cut, and an export that outlived what defined it. Remove the instances and add the guard that would have caught each.

### Phase `W04.P08` - remove duplicated and aliased declarations

Every surviving alias, pass-through export, and semantically duplicated declaration is removed or given one owner, so no behaviour is described in two places.

- [x] `W04.P08.S16` - Sweep the package for aliases that rename an existing binding, and repoint their callers at the original; `src/vaultspec_rag/cli/_app.py, src/vaultspec_rag/serviceclient/_discovery.py`.
- [x] `W04.P08.S17` - Search by meaning for declarations that restate logic owned elsewhere, and collapse each onto its owner; `src/vaultspec_rag/`.
- [x] `W04.P08.S18` - Confirm no non-facade module exports a name it does not define, and that the guard proves it; `src/vaultspec_rag/tests/test_no_reexports.py`.
- [x] `W04.P08.S21` - Make the test helpers that now cross module boundaries public, after establishing why narrowing the shared harness import destabilises distributed workers; `src/vaultspec_rag/tests/_jobs_tui_harness.py, src/vaultspec_rag/tests/test_cli_jobs_tui*.py`.

### Phase `W04.P09` - gate the regressions a split can introduce

A decorator orphaned by a line-range cut, and a test module growing past the production ceiling, are both invisible to today's gates. Each gets a guard proven to fail.

- [x] `W04.P09.S19` - Guard that an extraction cannot orphan a decorator onto the definition below it; `src/vaultspec_rag/tests/`.
- [x] `W04.P09.S20` - Bring every test module under the production module ceiling and gate them at it; `src/vaultspec_rag/tests/, pyproject.toml`.

## Parallelization

Waves are sequenced. Within W01, the clean job-manager step may proceed while the three shared-worktree handoffs are observed, because it has no import or state dependency on them. The two overlapping targets do not begin their split steps until their live changes are reconciled. Each integration scenario split follows the production seams it imports.

## Verification

Each completed production seam runs its direct consumer tests plus lint, formatting, and type checks. Each integration split runs its moved real-service scenarios. Completion requires a direct-import/re-export guard, a clean plan check, a formal code review, and `uv run python tools/health_report.py --fast --top 10` with none of the reported modules at MI 0.00.
