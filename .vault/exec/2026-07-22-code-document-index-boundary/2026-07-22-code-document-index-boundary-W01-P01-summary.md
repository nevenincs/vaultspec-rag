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

# `code-document-index-boundary` `W01.P01` summary

W01.P01 establishes typed, caller-configured content ownership and makes
invalid or unmigrated policy a mutation-free refusal at index and service-job
boundaries.

- Created: `src/vaultspec_rag/indexer/_content_policy.py`
- Created: `src/vaultspec_rag/indexer/_resolved_policy.py`
- Created: `src/vaultspec_rag/indexer/_file_state.py`
- Modified: `src/vaultspec_rag/config.py`
- Modified: `src/vaultspec_rag/_job_errors.py`
- Modified: `src/vaultspec_rag/indexer/_chunking.py`
- Modified: `src/vaultspec_rag/indexer/_ignore_specs.py`
- Modified: `src/vaultspec_rag/indexer/_preprocess_config.py`
- Modified: `src/vaultspec_rag/indexer/_config_epoch.py`
- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`
- Modified: `src/vaultspec_rag/jobs.py`
- Created: `src/vaultspec_rag/tests/test_content_policy.py`
- Modified: `src/vaultspec_rag/tests/test_preprocess_config.py`
- Created: `src/vaultspec_rag/tests/integration/test_content_policy_fail_closed.py`

## Description

The phase separates parser capability from admission, defines ordered explicit
routes and versioned source profiles, requires preprocessing ownership and
extractor versions, and rejects conflicting or legacy policy without fallback.
One immutable snapshot carries normalized ignore, routing, preprocessing,
decoder, execution-mode, membership, and content identities through code
execution. Explicit per-file convergence states distinguish successful,
policy-rejected, retryable, terminal, decode-failed, and chunk-failed work.

Public code-index and job gates validate policy before mutation authority, and
real-resource tests preserve existing collection identifiers, metadata,
extraction cache, canonical jobs, and durable job state on refusal. The single
phase-boundary invocation completed with 50 passed tests in 2.77 seconds.
