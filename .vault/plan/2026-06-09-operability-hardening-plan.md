---
tags:
  - '#plan'
  - '#operability-hardening'
date: '2026-06-09'
tier: L3
related:
  - '[[2026-06-09-operability-hardening-adr]]'
  - '[[2026-06-09-operability-hardening-research]]'
---

# `operability-hardening` `operability hardening` plan

## Description

Implements the targeted hardening authorised by the `operability-hardening` ADR and
grounded in the `operability-hardening` research: every active post-deconflation issue
across service lifecycle/management (#181, #166), runtime/environment/compatibility (#176,
#177, #178, #180), and CLI UX + documentation (#169, #170, #171, #172). The waves are
ordered so the daemon is first made reliably runnable (W01), then truthful and observable
(W02), then the CLI/docs are polished (W03), then the whole is re-validated (W04).

## Steps

## Wave `W01` - Runtime correctness

Make the resident daemon reliably runnable under the pinned Python interpreter;
foundational for all live-service work.

### Phase `W01.P01` - Daemon interpreter and environment

Spawn the daemon under the project venv interpreter and guard against incompatible
interpreters.

- [x] `W01.P01.S01` - Spawn the daemon with the project venv interpreter, not ambient sys.executable; `src/vaultspec_rag/cli/_process.py`.
- [x] `W01.P01.S02` - Add a defensive interpreter-version guard with an actionable error; `src/vaultspec_rag/store.py`.

### Phase `W01.P02` - Model-load resilience

Fail fast with remediation on gated models and ensure the in-process path loads the model.

- [x] `W01.P02.S03` - Wrap gated-model construction to fail fast with HF_TOKEN remediation; `src/vaultspec_rag/embeddings.py`.
- [x] `W01.P02.S04` - Idempotently load the embedding model before lease in background reindex; `src/vaultspec_rag/jobs.py`.

## Wave `W02` - Service lifecycle and management hardening

Make service lifecycle verbs truthful and the daemon observable and vacatable, especially
on Windows.

### Phase `W02.P03` - Lifecycle correctness quick-wins

Truthful exit codes, correct log routing, 400-not-500, and faster collection drop.

- [x] `W02.P03.S05` - Return non-zero exit when start is blocked by an occupied port; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `W02.P03.S06` - Route the logs admin tool to the JSON logs endpoint; `src/vaultspec_rag/cli/_http_search.py`.
- [x] `W02.P03.S07` - Convert missing project_root into a 400 with a clear message, not a 500; `src/vaultspec_rag/server/_routes.py, src/vaultspec_rag/server/_utils.py`.
- [x] `W02.P03.S08` - Remove the redundant pre-delete before dropping a collection; `src/vaultspec_rag/store.py`.

### Phase `W02.P04` - Observability and Windows detach

Orphan detection, token persistence, and Job-Object-safe detached spawning.

- [x] `W02.P04.S09` - Detect a healthy orphaned daemon via port probe when service.json is absent; `src/vaultspec_rag/cli/_service_lifecycle.py, src/vaultspec_rag/cli/_service_status.py`.
- [x] `W02.P04.S10` - Persist the service token into service.json during the start health-poll; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `W02.P04.S11` - Spawn the daemon with Windows Job-Object breakaway and an OSError fallback; `src/vaultspec_rag/cli/_process.py`.

## Wave `W03` - CLI UX and documentation

Flatten the CLI command tree, clean its help, document the indexing architecture, and add
persona UX tests.

### Phase `W03.P05` - CLI command-tree flatten

Collapse server service into server while preserving the genuine server mcp group.

- [x] `W03.P05.S12` - Collapse server service commands into server, preserving server mcp; `src/vaultspec_rag/cli/_app.py`.

### Phase `W03.P06` - CLI help cleanup

Move user-facing help into explicit Typer help and strip developer docstring sections.

- [x] `W03.P06.S13` - Move user-facing help into explicit Typer help and rich_help_panel and strip developer docstring sections; `src/vaultspec_rag/cli/`.

### Phase `W03.P07` - Indexing architecture documentation

Author a grounded indexing and retrieval guide and cross-reference it from help.

- [x] `W03.P07.S14` - Author the indexing and retrieval architecture guide and cross-reference from help; `docs/indexing.md`.

### Phase `W03.P08` - Testimonial CLI tests

Operator-persona end-to-end integration tests over the cleaned CLI, no mocks.

- [x] `W03.P08.S15` - Add operator-persona testimonial end-to-end CLI integration tests; `src/vaultspec_rag/tests/integration/`.

## Wave `W04` - Verification

Re-validate the live service end-to-end, code-review the changes, and reconcile the
addressed issues.

### Phase `W04.P09` - Verification and issue reconciliation

Re-run empirical validation, code review, and close the addressed issues.

- [ ] `W04.P09.S16` - Re-run empirical service validation, code review, and close addressed issues; `src/vaultspec_rag/`.

## Parallelization

Waves are sequenced (W01 → W02 → W03 → W04): each must land before the next begins. Within
a wave, phases that touch disjoint files may run in parallel; phases sharing a file are
serialised. Concretely: W01.P01 and W01.P02 are disjoint (parallel). In W02, P03 and P04
both touch `cli/_service_lifecycle.py`, so they are serialised; within each phase the steps
sharing that file (S05/S09/S10) run on one owner. W03.P05 (flatten) must land before
W03.P06 (help cleanup) since help is rewritten against the flattened tree; P07 (docs) and
P08 (tests) follow and depend on P05/P06. W04 runs last.

## Verification

The plan is complete when:

- Every Step in every Wave is closed (`- [x]`).
- `ruff` and `ty` are clean and the full test suite passes (real GPU + Qdrant, no mocks).
- The daemon spawns under the pinned interpreter; a gated/missing model fails fast with
  remediation; in-process background reindex loads the model.
- Lifecycle verbs return truthful exit codes; `service logs` shows content; missing
  `project_root` yields 400; the Windows daemon survives launching-shell exit.
- The CLI exposes flattened `server <cmd>` commands (with `server mcp` preserved) and clean
  `--help` with no leaked developer docstrings.
- The indexing architecture guide exists and is cross-referenced from help.
- The empirical service validation re-runs green, the code review signs off, and the
  addressed GitHub issues (#166, #169, #170, #171, #172, #176, #177, #178, #180, #181) are
  closed.
