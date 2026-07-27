---
generated: true
tags:
  - '#index'
  - '#storage-namespace-hygiene'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - '[[2026-07-14-storage-namespace-hygiene-P01-S01]]'
  - '[[2026-07-14-storage-namespace-hygiene-P01-S02]]'
  - '[[2026-07-14-storage-namespace-hygiene-P01-S03]]'
  - '[[2026-07-14-storage-namespace-hygiene-P01-S04]]'
  - '[[2026-07-14-storage-namespace-hygiene-P01-S05]]'
  - '[[2026-07-14-storage-namespace-hygiene-P01-S06]]'
  - '[[2026-07-14-storage-namespace-hygiene-P01-S07]]'
  - '[[2026-07-14-storage-namespace-hygiene-P01-summary]]'
  - '[[2026-07-14-storage-namespace-hygiene-P02-S08]]'
  - '[[2026-07-14-storage-namespace-hygiene-P02-S09]]'
  - '[[2026-07-14-storage-namespace-hygiene-P02-S10]]'
  - '[[2026-07-14-storage-namespace-hygiene-P02-summary]]'
  - '[[2026-07-14-storage-namespace-hygiene-adr]]'
  - '[[2026-07-14-storage-namespace-hygiene-audit]]'
  - '[[2026-07-14-storage-namespace-hygiene-plan]]'
  - '[[2026-07-14-storage-namespace-hygiene-research]]'
---

# `storage-namespace-hygiene` feature index

Auto-generated index of all documents tagged with `#storage-namespace-hygiene`.

## Documents

### adr

- `2026-07-14-storage-namespace-hygiene-adr` - `storage-namespace-hygiene` adr: `survey snapshot cache and per-root teardown` | (**status:** `accepted`)

### audit

- `2026-07-14-storage-namespace-hygiene-audit` - `storage-namespace-hygiene` audit: `survey snapshot cache and delete --root review`

### exec

- `2026-07-14-storage-namespace-hygiene-P01-S01` - Add the survey snapshot slot: classified survey list plus computed_at, atomic reference swap, thread-safe accessor
- `2026-07-14-storage-namespace-hygiene-P01-S02` - Publish the maintenance cycle's survey into the snapshot slot and add the one-shot startup warmer (survey-only, read-only)
- `2026-07-14-storage-namespace-hygiene-P01-S03` - Wire the warmer task into lifespan startup and shutdown alongside the maintenance task
- `2026-07-14-storage-namespace-hygiene-P01-S04` - Serve the storage survey route from the snapshot with filters applied to the cached list, add computed_at and source envelope fields, and implement the fresh=true recompute-and-publish path
- `2026-07-14-storage-namespace-hygiene-P01-S05` - Pass a --fresh flag through the CLI survey verb and the transport query builder in serviceclient/\_transport.py
- `2026-07-14-storage-namespace-hygiene-P01-S06` - Unit-test snapshot swap semantics, cached-list filtering, and freshness metadata alongside the routes tests
- `2026-07-14-storage-namespace-hygiene-P01-S07` - Integration-test the live daemon serving the cached survey after warmup and recomputing on fresh=true
- `2026-07-14-storage-namespace-hygiene-P01-summary` - `storage-namespace-hygiene` `P01` summary
- `2026-07-14-storage-namespace-hygiene-P02-S08` - Add --root to the storage delete verb: normalize the root exactly as registration does, resolve via root_collection_prefix, dispatch through delete_prefix, and make an absent namespace an idempotent exit-0 already_absent success in both human and json modes with resolved prefix and queried root in the envelope
- `2026-07-14-storage-namespace-hygiene-P02-S09` - Test the delete --root matrix: resolution parity with registration, removed, already_absent exit 0, unknown refusal, and json envelope shape
- `2026-07-14-storage-namespace-hygiene-P02-S10` - Document delete --root harness-teardown recipe and the survey freshness semantics across docs/cli.md and docs/storage-maintenance.md
- `2026-07-14-storage-namespace-hygiene-P02-summary` - `storage-namespace-hygiene` `P02` summary

### plan

- `2026-07-14-storage-namespace-hygiene-plan` - `storage-namespace-hygiene` plan

### research

- `2026-07-14-storage-namespace-hygiene-research` - `storage-namespace-hygiene` research: `dashboard survey latency and namespace removal asks`
