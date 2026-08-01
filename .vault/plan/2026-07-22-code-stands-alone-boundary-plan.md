---
tags:
  - '#plan'
  - '#code-stands-alone-boundary'
date: '2026-07-22'
modified: '2026-07-27'
body_hash: 'sha256:92e2cc33639a5ce67f326a1f3b0f700632aaa2f9ea71940b3a45f37735796220'
tier: L1
related:
  - '[[2026-07-22-codebase-dedup-centralization-audit]]'
  - '[[2026-07-23-code-stands-alone-boundary-adr]]'
  - '[[2026-07-27-code-stands-alone-boundary-grounding-research]]'
---

# `code-stands-alone-boundary` plan

## Description

No separate description is recorded in the retained prior plan body. Source: retained prior plan body.

## Steps

- [x] `S01` - Enumerate every source, test, and configuration file citing a development record by identifier, and record the constraint each citation was standing in for; `src/vaultspec_rag`.
- [x] `S02` - Replace the citations in the package and command-line modules with the constraint stated directly, so a reader learns the rule rather than where it was decided; `src/vaultspec_rag/cli/_core.py, src/vaultspec_rag/cli/__init__.py, src/vaultspec_rag/commands/_provision.py`.
- [x] `S03` - Replace the citations in the indexer, search, and server modules on the same basis; `src/vaultspec_rag/indexer/__init__.py, src/vaultspec_rag/search/__init__.py, src/vaultspec_rag/server/_lifecycle.py, src/vaultspec_rag/server/_lifespan.py, src/vaultspec_rag/server/_main.py, src/vaultspec_rag/server/_models.py`.
- [x] `S04` - Replace the citations in the test modules, keeping synthetic vault paths that are legitimate test data; `src/vaultspec_rag/tests`.
- [x] `S06` - Remove development-record citations from the mcp package docstrings and comments, keeping any protocol-tool names that are runtime contract rather than record references; `src/vaultspec_rag/mcp`.
- [x] `S07` - Sweep the citations skipped during the main pass because their files carried concurrent in-flight index and lifecycle work, once that work has settled; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_streaming.py, src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/server/_lifespan.py`.
- [x] `S05` - Guard the boundary with a check that fails when a tracked source file names a development record, so the invariant is enforced rather than asserted; `src/vaultspec_rag/tests/test_adr_regression.py`.

## Parallelization

No separate parallelization is recorded in the retained prior plan body. Source: retained prior plan body.

## Verification

No separate verification is recorded in the retained prior plan body. Source: retained prior plan body.
