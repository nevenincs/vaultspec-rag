---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

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
