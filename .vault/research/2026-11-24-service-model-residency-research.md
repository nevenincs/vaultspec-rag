---
tags:
  - '#research'
  - '#service-model-residency'
date: '2026-11-24'
modified: '2026-11-24'
body_schema: 'body-v2'
body_hash: 'sha256:e031dbda05dd165de3471472e566e8d305b0e6efca5f6230a607f397f0a3f9b0'
related: []
---
# `service-model-residency` research: `Where the accelerator lane spends its time`

## Question

How much of the accelerator test lane is spent starting services and loading models, and how many of its tests need an accelerator at all?

## Findings

- **The last complete accelerator lane took 97 minutes.** The resident-model tier ran 888 tests in 49 min 33 s and the spawned-service tier ran 82 tests in 43 min 17 s. Locator: GitHub Actions run 41405337940, job 126019652353, step "Run GPU test tier through guarded coordinator", 2026-11-03.
- **Service starts dominate the spawned-service tier.** The shared daemon fixture was set up 10 times at a median of 27.4 s (4 min 39 s in total), and two further module daemons took 26 s each. Same job, "fixture duration top" table of the second selection.
- **Tests whose subject is the service account for about 20 minutes of that tier.** The restart file took about 8.5 minutes across 5 starting cases, the eviction file about 4 minutes, the runtime lifecycle file about 5 minutes and the discovery file about 3 minutes. Same job, "test call duration top" table.
- **A service start loads the full model set unconditionally.** `src/vaultspec_rag/server/_lifespan.py:520` loads the dense and sparse encoders, then the reranker when enabled, before the service reports ready; no setting skips it.
- **One third of the lane needs no accelerator.** The whole lane was run on 12 hosted machines with no accelerator and the model cache offline: of 632 tests, 204 passed, 364 errored in setup on model acquisition, 61 failed and 3 skipped. Locator: GitHub Actions run 45366318009, 2026-11-24.
- **The service already releases and re-warms its models.** A GPU borrow pauses the service, releases its VRAM and warms it again on resume, as `2026-07-24-service-quiesce-adr` specifies.

## Options

- Keep eager loading and reduce the number of starts in the tests.
- Make prewarm optional, on by default, so service tests can start without loading models.
- Release resident models after an idle interval through the existing release.

## Sources

- GitHub Actions run 41405337940, job 126019652353 (vaultspec-rag 0.6.5 release hardware tier).
- GitHub Actions run 45366318009 (accelerator lane run with no accelerator).
- `src/vaultspec_rag/server/_lifespan.py:520`
- `src/vaultspec_rag/tests/integration/conftest.py:780`
