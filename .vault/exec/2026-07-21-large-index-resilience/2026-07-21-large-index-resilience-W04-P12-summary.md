---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:d279b4ec12d7cf43bfe0cd03cee660a4c5fb0c2645c17cb7cd5cc8870c7dde83'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` `W04.P12` summary

Named support profiles now bind independent code and document workload limits to backend, host, disk, source, generated-chunk, and weighted-byte dimensions. Code discovery measures admitted source work without reading corpus contents, bounded production measures generated work without retaining the corpus, and service admission refuses unsupported work before durable creation or GPU loading.

- Created: `src/vaultspec_rag/index_profiles.py`
- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`
- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/job_dispatch.py`
- Modified: `src/vaultspec_rag/server/_routes.py`
- Created: `src/vaultspec_rag/tests/integration/test_index_support_admission.py`
- Modified: `src/vaultspec_rag/tests/test_index_profiles.py`

## Description

The phase established two closed named profiles with per-domain limits, immutable full and scoped source measurements, runtime generated-work measurement, and stable refusal mappings. The boundary passed 10 cases, including structured pre-creation refusal and real CUDA/Qdrant checkpoint preservation. Ruff, formatting, and type checks passed; the repository-wide complexity gate continues to report its existing broad baseline.
