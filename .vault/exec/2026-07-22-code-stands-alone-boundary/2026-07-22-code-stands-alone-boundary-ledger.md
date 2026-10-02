---
tags:
  - '#exec'
  - '#code-stands-alone-boundary'
date: '2026-07-22'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:51b0d539234b07c9fe937faf3283103a2e435ff4e7f3930307e88fb45d1986a1'
related:
  - "[[2026-07-22-code-stands-alone-boundary-plan]]"
---

# `code-stands-alone-boundary` ledger

## Changes

- `S01` `A` `.vault/audit/2026-07-22-codebase-dedup-centralization-audit.md`
- `S02` `M` `src/vaultspec_rag/cli/_core.py`
- `S03` `M` `src/vaultspec_rag/server/_lifecycle.py`
- `S04` `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `S05` `A` `tools/citation_gate.py`
- `S06` `M` `src/vaultspec_rag/mcp/_admin_client.py`
- `S07` `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Notes

- `S01` Historical attribution: 074f99f2f4bf17007f9629cac2e7231ef55f2274 fix(indexer): collapse the code-kind admission guard to one owner. Actual retained operation only; no original runtime PASS or whole-Step acceptance inferred. Audit establishes a narrow citation finding and inventory, not enumeration of every source/test/config citation and its constraint.
- `S02` Historical attribution: d3842a7b7f6c1b17d3eacb82f7ada0e937f5e106 docs(cli): strip development-record citations from module docstrings. Actual retained operation only; no original runtime PASS or whole-Step acceptance inferred.
- `S03` Historical attribution: 9250249c8e458d8e8025f739b99b0b51772b5518 docs(indexer): strip development-record citations from module docstrings. Actual retained operation only; no original runtime PASS or whole-Step acceptance inferred.
- `S04` Historical attribution: e76d6a71d31c5e48c465ea07c2ef404df45089f4 fix(index)+docs(tests): define `is_cuda_out_of_memory;` strip citations from test docstrings. Actual retained operation only; no original runtime PASS or whole-Step acceptance inferred.
- `S05` Historical attribution: 0195cab20bcc69a045b2373a751554e108d29edc feat(lint): gate code-stands-alone citations. Actual retained operation only; no original runtime PASS or whole-Step acceptance inferred. Guard implemented in `tools/citation_gate.py` and justfile rather than planned test path.
- `S06` Historical attribution: 25349c1fc5b090e4b04c70b0e9369abd19194baa docs(mcp): strip development-record citation from admin-client docstring. Actual retained operation only; no original runtime PASS or whole-Step acceptance inferred.
- `S07` Historical attribution: 2481e48653cb2cc0cb38286ae7656206638c32dd refactor(index): strip development-record citations from indexer and lifespan (S07). Actual retained operation only; no original runtime PASS or whole-Step acceptance inferred. Retained change touches codebase indexer and lifespan only; no streaming/document change inferred.
