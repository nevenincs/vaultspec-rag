---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace large-index-resilience with a kebab-case feature tag, e.g. #foo-bar.
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
