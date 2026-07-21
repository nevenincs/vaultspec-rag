---
tags:
  - '#plan'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
tier: L3
related:
  - '[[2026-07-21-managed-log-contract-adr]]'
  - '[[2026-07-21-managed-log-contract-research]]'
  - '[[2026-07-21-managed-log-contract-reference]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `managed-log-contract` plan

Bound every managed log and give operators one truthful service-plus-Qdrant view both while
the daemon is live and after it stops.

## Wave `W01` - bound both managed log writers

Establish the shared clean-break retention policy and make the supervised Qdrant writer obey it; every operator-surface wave depends on these durable storage guarantees.

### Phase `W01.P01` - replace service-specific retention configuration

Expose one generic managed-log policy and wire the service logger to the renamed settings without aliases.

- [x] `W01.P01.S01` - Replace service-only retention settings and environment names with the generic managed-log contract; `src/vaultspec_rag/config.py`.
- [x] `W01.P01.S02` - Install the service log handler from the generic managed-log settings; `src/vaultspec_rag/server/_main.py`.
- [x] `W01.P01.S03` - Assert generic defaults, environment overrides, and removal of legacy configuration names; `src/vaultspec_rag/tests/test_config.py`.

### Phase `W01.P02` - rotate supervised Qdrant output

Give the raw child-output drain a secure independently rotating sink while preserving uninterrupted recent-output diagnostics.

- [x] `W01.P02.S04` - Implement bounded raw-byte rotation and configure the Qdrant supervisor from the shared retention policy; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [x] `W01.P02.S05` - Exercise real Qdrant-output rollover, retention, restart append, and diagnostic continuity; `src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py`.

## Wave `W02` - unify live and offline operator views

Replace service-only retrieval with one bounded source-aware service-domain contract, then expose that contract consistently through HTTP, transport, and CLI after the writer guarantees land.

### Phase `W02.P03` - build the source-aware reader

Read sparse rotated generations for service, Qdrant, or grouped all-source views within the requested line bound.

- [x] `W02.P03.S06` - Replace the legacy service-only reader with bounded source-aware grouped log retrieval; `src/vaultspec_rag/logging_config.py`.
- [x] `W02.P03.S07` - Filter source-tagged groups without merging or fabricating chronology; `src/vaultspec_rag/server/_routes_logs.py`.
- [x] `W02.P03.S08` - Verify sparse backup discovery, per-source limits, grouped output, and malformed-source rejection; `src/vaultspec_rag/tests/test_logging_config.py`.

### Phase `W02.P04` - expose one authenticated live contract

Carry the source selector and grouped payload through the existing authenticated admin routes and import-light transport.

- [x] `W02.P04.S09` - Serve source-aware plain and JSON log responses from the shared reader; `src/vaultspec_rag/server/_routes.py`.
- [x] `W02.P04.S10` - Carry the source selector and structured log outcome through the admin transport; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `W02.P04.S11` - Verify authenticated live responses, bounds, filters, and source-group schema; `src/vaultspec_rag/tests/integration/test_service_logs.py`.

### Phase `W02.P05` - make CLI logs work live and post-crash

Replace parsed service activity with explicit source selection, grouped raw rendering, and local fallback through the production reader.

- [x] `W02.P05.S12` - Replace the legacy activity parser and raw compatibility flag with grouped source rendering and offline fallback; `src/vaultspec_rag/cli/_service_logs.py`.
- [x] `W02.P05.S13` - Update in-process CLI contract coverage for source selection and local post-crash reads; `src/vaultspec_rag/tests/test_cli_server.py`.

## Wave `W03` - publish and verify the clean-break contract

Update operator-facing references for the renamed configuration and source-aware command, then run focused and full quality gates before formal review.

### Phase `W03.P06` - update operator documentation

Document the generic retention budget and the unified live/offline log workflow without preserving removed names or flags.

- [x] `W03.P06.S14` - Document generic managed-log environment variables and aggregate retention semantics; `docs/configuration.md`.
- [x] `W03.P06.S15` - Document source selection, grouped output, JSON shape, and removal of the raw flag; `docs/cli.md`.
- [ ] `W03.P06.S16` - Document live and post-crash service plus Qdrant log inspection; `docs/service-mode.md`.

### Phase `W03.P07` - close regression and quality gates

Prove real rollover and operator behavior across supported paths, validate the vault artifacts, and complete formal review.

- [ ] `W03.P07.S17` - Run focused unit and integration suites for configuration, writers, routes, transport, and CLI; `src/vaultspec_rag/tests`.
- [ ] `W03.P07.S18` - Run repository formatting, lint, type, and complete test gates required by project configuration; `pyproject.toml`.
- [ ] `W03.P07.S19` - Validate managed-log vault artifacts and feature index integrity; `.vault`.
- [ ] `W03.P07.S20` - Record formal safety, intent, and quality review findings; `.vault/audit`.

## Description

Implement the accepted clean-break managed-log architecture in three ordered Waves. The first
renames the service-specific retention configuration and applies the same independent byte and
backup limits to service and supervised Qdrant output. The second replaces the legacy
service-only reader and parsed activity feed with a bounded source-aware contract shared by
authenticated HTTP, the import-light client, and offline CLI fallback. The third updates the
operator references and closes repository and architecture quality gates.

The two sources remain separate and retain their own rotation sequences. An all-source view
groups them by source and never implies cross-process chronology. Removed configuration names,
payload shapes, parsing paths, and the raw compatibility flag receive no aliases or migration
code.

## Steps

The canonical Step rows are grouped under the three Waves above and are updated only through
the plan CLI during execution.

## Parallelization

Waves execute in order. Within W01, configuration renaming precedes both service and Qdrant
wiring; the writer-specific production and test Steps can then proceed independently. Within
W02, the reader lands before routes, transport, or CLI consume its shape. Route and transport
work is sequential, while CLI implementation may proceed in parallel once the reader contract
is fixed. Documentation files in W03 can be updated independently after W02; every quality
gate and the formal review wait for all code, tests, and documentation.

## Verification

- Production-behavior tests force service and Qdrant rollover at small limits and prove each
  source retains no more than one active file plus the configured backup count.
- Configuration tests prove only the generic managed-log names remain and that the same values
  independently govern both writers.
- Reader and endpoint tests prove sparse numeric generations are discovered, each source is
  bounded, all-source output remains grouped, filters stay bounded, and invalid selectors fail
  structurally.
- CLI tests prove live authenticated reads and local post-crash reads expose the same source
  contract with truthful human and JSON outcomes.
- Repository searches find no legacy retention names, service-only reader, activity parser, or
  raw compatibility option in production code or operator documentation.
- Targeted and full tests, formatting, lint, strict type checks, plan and vault validation, and
  formal code review pass with no unresolved critical or high findings.
- Every Step is closed through the plan CLI before the plan is reported complete.
