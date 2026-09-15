---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:39bada94048dd6829d0189ff0de35792efe615bd5004191755861f92959b0dda'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# `generation-accounting` ledger

## Changes

- `S01` `T`
- `S02` `T` `src/vaultspec_rag/indexer/_drift_owner.py`
- `S03` `T`
- `S04` `T`
- `S05` `T` `src/vaultspec_rag/tests/test_run_checkpoint.py`
- `S06` `T` `src/vaultspec_rag/tests/test_search_timeout.py`
- `S07` `T`
- `S08` `T` `src/vaultspec_rag/tests/test_run_checkpoint.py`
- `S09` `T` `src/vaultspec_rag/store_ingest.py`
- `S10` `T`
- `S11` `T`
- `S12` `T`
- `S13` `T`
- `S14` `T`
- `S15` `T`
- `S16` `T`

## Notes

- `S01` Verification passed: scoped Ruff format and lint checks, `ty`, strict basedpyright,
- `S01` and `test_run_checkpoint.py` (25 passed).
- `S03` Focused format, lint, strict type, and existing reindex transport coverage passed.
- `S04` Scoped Ruff format, Ruff lint, `ty`, strict basedpyright, and the direct
- `S04` real-storage guard demonstration passed. The focused pytest selection was
- `S04` blocked before execution by the GPU-tier fail-closed guard: the resident
- `S04` service release is `0.4.21`, while this checkout requires `0.4.15`.
- `S07` Focused formatting, lint, strict type checking, and checkpoint tests pass. The focused
- `S07` regression proof for retained empty sources is owned by the following test step.
- `S10` The focused integration test is fail-closed on this host: pytest exits before collection
- `S10` because no ready compatible machine-pointer service is available. No binary was installed
- `S10` or bypassed, so the guard-failure demonstration also remains unavailable here.
- `S11` Focused formatting, lint, `ty`, and strict `basedpyright` checks passed. The relevant integration selection correctly refused before collection because no compatible resident machine-pointer service was captured; `test_run_checkpoint.py` completed with 28 passing unit tests.
- `S12` The focused runtime command stopped before test collection with the repository GPU/service guard; it was not bypassed. The guard demonstration remains documented beside the exact assertions: restoring pre-swap route reconciliation deletes the old served code and cannot retire the still-private replacement's document origin.
- `S13` Focused static and unit gates passed. The integration regression is owned by the following
- `S13` test step.
- `S14` The collection-backed integration selection is subject to the repository's compatible
- `S14` resident-service guard; static checks still cover the authored test on this host.
- `S15` The associated prefix-form regression is tracked separately as S16.
- `S16` The integration selection uses the repository's pinned Qdrant service guard and is not
- `S16` bypassed when that compatible service is unavailable.
