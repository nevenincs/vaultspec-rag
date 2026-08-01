---
tags:
  - '#plan'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-27'
body_hash: 'sha256:54d7d8204266620755aba62fc88a2e13b8ba107c7703e50b885459479955beff'
tier: L2
related:
  - '[[2026-07-14-storage-namespace-hygiene-adr]]'
  - '[[2026-07-14-storage-namespace-hygiene-research]]'
---

# `storage-namespace-hygiene` plan

## Description

Implements the accepted storage-namespace-hygiene decision (see the ADR and
research in related). P01 makes the storage survey O(1): the daemon holds a
survey snapshot (list plus computed_at) that the maintenance cycle publishes
instead of discarding, a one-shot startup warmer fills the cold slot, and the
route serves the snapshot with filters applied post-cache, honest freshness
metadata, and a fresh=true recompute path. P02 gives consumers and test
harnesses a sanctioned, idempotent per-root teardown by adding root
addressing to the existing storage delete verb, then documents both. The HTTP
plane stays read-only; no destruction route is added.

## Steps

### Phase `P01` - Survey snapshot cache

Publish the maintenance survey into daemon state, warm it at startup, and serve the route O(1) with freshness metadata

- [x] `P01.S01` - Add the survey snapshot slot: classified survey list plus computed_at, atomic reference swap, thread-safe accessor; `src/vaultspec_rag/server/_state.py`.
- [x] `P01.S02` - Publish the maintenance cycle's survey into the snapshot slot and add the one-shot startup warmer (survey-only, read-only); `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `P01.S03` - Wire the warmer task into lifespan startup and shutdown alongside the maintenance task; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P01.S04` - Serve the storage survey route from the snapshot with filters applied to the cached list, add computed_at and source envelope fields, and implement the fresh=true recompute-and-publish path; `src/vaultspec_rag/server/_routes.py`.
- [x] `P01.S05` - Pass a --fresh flag through the CLI survey verb and the transport query builder in serviceclient/\_transport.py; `src/vaultspec_rag/cli/_service_storage.py`.
- [x] `P01.S06` - Unit-test snapshot swap semantics, cached-list filtering, and freshness metadata alongside the routes tests; `src/vaultspec_rag/tests/test_storage_ops.py`.
- [x] `P01.S07` - Integration-test the live daemon serving the cached survey after warmup and recomputing on fresh=true; `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`.

### Phase `P02` - Per-root teardown and docs

Root-addressed idempotent namespace delete on the existing CLI verb, plus documentation of teardown and survey freshness

- [x] `P02.S08` - Add --root to the storage delete verb: normalize the root exactly as registration does, resolve via root_collection_prefix, dispatch through delete_prefix, and make an absent namespace an idempotent exit-0 already_absent success in both human and json modes with resolved prefix and queried root in the envelope; `src/vaultspec_rag/cli/_service_storage.py`.
- [x] `P02.S09` - Test the delete --root matrix: resolution parity with registration, removed, already_absent exit 0, unknown refusal, and json envelope shape; `src/vaultspec_rag/tests/test_storage_adversarial.py`.
- [x] `P02.S10` - Document delete --root harness-teardown recipe and the survey freshness semantics across docs/cli.md and docs/storage-maintenance.md; `docs/cli.md`.

## Parallelization

P01 carries hard ordering S01 -> S02 -> S03 -> S04 (state slot before
writers before lifespan wiring before the route reader); S05 follows S04.
S06 and S07 follow the code they test. P02 is independent of P01 and may run
in parallel with it; within P02, S08 precedes S09, and S10 (docs) lands last
so it documents the shipped behavior of both phases.

## Verification

- Unit and integration suites pass, including the new snapshot, route
  freshness, and delete --root tests; no skips added.
- A live daemon serves /storage/survey from cache sub-second after warmup at
  a many-namespace store, and fresh=true visibly recomputes (computed_at
  advances).
- delete --root on an absent namespace exits 0 with a structured
  already-absent envelope in json mode; unknown namespaces remain refused
  without --allow-unknown.
- Lifecycle-inertness regression tests stay green (maintenance import graph
  still excludes vaultspec_rag.cli).
- Lint, type, complexity, and vault checks green; docs updated in the same
  cycle.
