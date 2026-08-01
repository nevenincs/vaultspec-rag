---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:6ddfc9906883ecd237c3590b18b948eb5949e7e02dd7ea9cdb8749135dade7e1'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` `W06.P12` summary

The document workload now has independent operability, resource admission,
measured acceptance, lifecycle isolation, and restart evidence.

- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/server/_lifespan.py`
- Modified: `src/vaultspec_rag/tests/test_server.py`
- Modified: `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`
- Created: `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py`
- Created: `src/vaultspec_rag/tests/integration/test_document_resource_bounds.py`
- Created: `src/vaultspec_rag/tests/integration/test_document_lifecycle.py`

## Description

Service health exposes separate code and document ceilings. Admission rejects
over-budget document work before model or extractor activity. The named
document workload measures every declared resource dimension and proves a real
CUDA and Qdrant interruption resumes the same generation. Code-only indexing
and cleanup preserve document storage, metadata, and cache state, while both
content kinds replay only their final unconfirmed durable unit.

Scoped Ruff and Ty checks passed. CPU resource and restart tests passed. The
serialized GPU phase completed four files and ten chunks, resumed from one to
ten confirmed units, and the lifecycle isolation test passed before full model
and store teardown.
