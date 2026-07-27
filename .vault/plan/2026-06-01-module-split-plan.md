---
tags:
  - '#plan'
  - '#module-split'
date: '2026-06-01'
modified: '2026-07-27'
tier: L2
related:
  - '[[2026-06-01-module-split-adr]]'
  - '[[2026-06-01-module-split-audit]]'
  - '[[2026-06-01-module-split-research]]'
  - '[[2026-07-27-module-split-production-length-gate-research]]'
---

# `module-split` `decompose overlength modules into direct owners` plan

## Description

The completed historical phases used a facade pattern that the amended ADR now
rejects. The remaining phases split every listed overlength module into
concrete owners, migrate all callers directly, and delete each former monolith
without retaining compatibility paths. Test modules are split by independently
collectable behavior domain; the production moves preserve the existing service,
storage, and index-lifecycle ownership decisions.

## Steps

Each new step moves one cohesive source or test module to direct concrete
owners, migrates its callers in the same change, and gates on real behavior
tests plus format, lint, and type checks. The historical phases document the
superseded facade work and remain closed; they are not a template for the
remaining phases.

### Phase `P01` - split commands.py (validate pattern)

Split commands.py into a commands/ package re-exporting the verbatim public surface; lowest-risk first to validate the pattern.

- [x] `P01.S01` - Split into a package re-exporting the verbatim public surface, then verify full suite + ruff + ty green; `src/vaultspec_rag/commands.py`.

### Phase `P02` - split torch_config.py

Split torch_config.py into a package; pure functions, no module state.

- [x] `P02.S02` - Split into a package re-exporting the verbatim public surface, then verify full suite + ruff + ty green; `src/vaultspec_rag/torch_config.py`.

### Phase `P03` - split search.py

Split search.py into a package; VaultSearcher plus orthogonal pure helpers.

- [x] `P03.S03` - Split into a package re-exporting the verbatim public surface, then verify full suite + ruff + ty green; `src/vaultspec_rag/search.py`.

### Phase `P04` - split indexer.py

Split indexer.py into a package; VaultIndexer/CodebaseIndexer with shared AST constants.

- [x] `P04.S04` - Split into a package re-exporting the verbatim public surface, then verify full suite + ruff + ty green; `src/vaultspec_rag/indexer.py`.

### Phase `P05` - split cli.py

Split the cli.py monolith into a package; preserve Typer app nesting and 24 external symbols.

- [x] `P05.S05` - Split into a package preserving Typer app nesting and all external symbols, then verify full suite + ruff + ty green; `src/vaultspec_rag/cli.py`.

### Phase `P06` - split mcp_server.py

Split mcp_server.py into a package; preserve the FastMCP mcp global, tool registration, and the :main entry point.

- [x] `P06.S06` - Split into a package preserving the FastMCP mcp global, tool registration, and the main entry point, then verify full suite + ruff + ty green; `src/vaultspec_rag/mcp_server.py`.

### Phase `P07` - split process-probe guard tests

Move independent canonical-source guard domains into directly collected test modules.

- [x] `P07.S07` - Split canonical process-probe guard domains into directly collected test modules and concrete shared helpers; `src/vaultspec_rag/tests/test_process_probe_canonical.py`.

### Phase `P08` - split installation integration tests

Separate installer behavior domains while retaining real workspace behavior coverage.

- [x] `P08.S08` - Split installation integration behavior domains into directly collected modules; `src/vaultspec_rag/tests/integration/test_install.py`.

### Phase `P09` - split jobs tests

Separate unit and service jobs behavior without test facades.

- [x] `P09.S09` - Split job-manager unit behavior domains into directly collected modules; `src/vaultspec_rag/tests/test_jobs_unit.py`.
- [x] `P09.S10` - Split service jobs integration behavior domains into directly collected modules; `src/vaultspec_rag/tests/integration/test_service_jobs.py`.

### Phase `P10` - split service lifecycle tests

Separate lifecycle acceptance domains while preserving real process proof.

- [x] `P10.S11` - Split service lifecycle integration behavior domains into directly collected modules; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

### Phase `P11` - decompose job management

Move job models and responsibilities to direct concrete owners and migrate callers.

- [x] `P11.S12` - Decompose job-management responsibilities and migrate all direct importers; `src/vaultspec_rag/job_manager.py`.

### Phase `P12` - decompose storage operations

Move storage lifecycle responsibilities to direct owners without changing service authority.

- [x] `P12.S13` - Decompose storage-operation responsibilities and migrate all direct importers; `src/vaultspec_rag/storage_ops.py`.

### Phase `P13` - decompose the store

Extract cohesive store collaborators and migrate direct consumers without a store facade.

- [x] `P13.S14` - Decompose store responsibilities and migrate all direct importers; `src/vaultspec_rag/store.py`.

### Phase `P14` - decompose watcher control

Separate watcher event intake, retry, and managed indexing owners.

- [x] `P14.S15` - Decompose watcher responsibilities and migrate all direct importers; `src/vaultspec_rag/watcher.py`.

### Phase `P15` - decompose run ledger

Separate run-ledger internals after the active ledger edit is integrated.

- [x] `P15.S16` - Decompose run-ledger responsibilities and migrate all direct importers after the active edit lands; `src/vaultspec_rag/indexer/_run_ledger.py`.

## Parallelization

The independent test-file phases may run in parallel. Production moves run in
dependency order, with `job_manager` before `watcher`, storage operations
before `store`, and the run-ledger move only after the existing concurrent
ledger edit is integrated.

## Verification

The plan is complete when every open step is closed. Each phase must leave no
forwarding import path, pass the affected real behavior suite, and pass format,
lint, and type checks. The final validation reruns the full length census and
the no-reexports guard.
