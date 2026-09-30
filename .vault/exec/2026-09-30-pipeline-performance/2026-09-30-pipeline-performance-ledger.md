---
tags:
  - '#exec'
  - '#pipeline-performance'
date: '2026-09-30'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:56c3b22f2745b7ebb51c97eb9a8ce5150fd73e963fafac6dac5f36dd3cfa1c16'
related:
  - "[[2026-09-30-pipeline-performance-plan]]"
---

# `pipeline-performance` ledger

## Changes

- `S01` `A` `dev/gpu_pipeline_profile.py`
- `S01` `A` `dev/_profile_tools.py`
- `S01` `A` `dev/_profile_workloads.py`
- `S01` `A` `src/vaultspec_rag/tests/test_gpu_profile_harness.py`
- `S01` `A` `.vault/research/2026-09-30-pipeline-performance-research.md`
- `S01` `A` `.vault/plan/2026-09-30-pipeline-performance-plan.md`
- `S01` `A` `.vault/index/pipeline-performance.index.md`
- `S01` `verify:` `pytest test_gpu_profile_harness.py: 11 tests` -> `pass`
- `S01` `verify:` `ruff check src dev tools` -> `pass`
- `S01` `verify:` `ruff format --check src dev tools` -> `pass`
- `S01` `verify:` `ty check profiling tools and harness tests` -> `pass`
- `S01` `verify:` `profile tool guard mutation intended failures and restored passes: 5 cases` -> `pass`
- `S01` `verify:` `cpu profiling CLI unprofiled smoke: 7 rounds` -> `pass`
- `S01` `by:` `vaultspec-high-executor`
- `S01` `A` `.vault/audit/2026-09-30-pipeline-performance-audit.md`
- `S01` `verify:` `pytest profiling harness and AST unit tests: 74 tests` -> `pass`
- `S01` `verify:` `consumer teardown guard intended failures and restored passes: 2 cases` -> `pass`
- `S01` `verify:` `independent re-review closes borrowed-lifetime high finding` -> `pass`
- `S02` `M` `src/vaultspec_rag/indexer/_ast_chunker.py`
- `S02` `M` `src/vaultspec_rag/tests/test_indexer_unit_chunking.py`
- `S02` `M` `.vault/research/2026-09-30-pipeline-performance-research.md`
- `S02` `verify:` `exact AST tuple parity on 820 sources at 5 budgets` -> `pass`
- `S02` `verify:` `20 paired CPU rounds and 36 default-budget repeat pairs` -> `pass`
- `S02` `verify:` `pytest profiling harness and AST unit tests: 74 tests` -> `pass`
- `S02` `by:` `vaultspec-high-executor`
- `S01` `verify:` `isolated profiling harness pytest13` -> `pass`
- `S01` `verify:` `isolated Ruff lint and format` -> `pass`
- `S01` `verify:` `isolated focused ty with existing environment` -> `pass`
- `S01` `M` `dev/_profile_tools.py`
- `S01` `M` `dev/gpu_pipeline_profile.py`
- `S01` `M` `src/vaultspec_rag/tests/test_gpu_profile_harness.py`
- `S01` `M` `.vault/research/2026-09-30-pipeline-performance-research.md`
- `S01` `M` `.vault/audit/2026-09-30-pipeline-performance-audit.md`
- `S01` `verify:` `Ruff lint and format on src dev tools` -> `pass`
- `S01` `verify:` `focused ty using existing interpreter` -> `pass`
- `S01` `verify:` `pytest harness and AST focused tests74` -> `pass`
- `S01` `verify:` `nonblocking and no-native guard intended failures and restored passes2` -> `pass`
- `S01` `verify:` `verified pinned native CPU sampling and corrected nonblocking source-stable sampling` -> `pass`
- `S02` `M` `.vault/audit/2026-09-30-pipeline-performance-audit.md`
- `S02` `M` `.vault/plan/2026-09-30-pipeline-performance-plan.md`
- `S02` `verify:` `Ruff lint and format src dev tools` -> `pass`
- `S02` `verify:` `focused ty current AST and tests` -> `pass`
- `S02` `verify:` `pytest harness and AST83` -> `pass`
- `S02` `verify:` `unchanged AST hash exact820input parity at5budgets and paired CPU timings` -> `pass`
- `S02` `verify:` `independent GPT6.1 Sol S02 review` -> `pass`
- `S03` `M` `dev/gpu_pipeline_profile.py`
- `S03` `M` `src/vaultspec_rag/embeddings.py`
- `S03` `M` `src/vaultspec_rag/config/_types.py`
- `S03` `M` `src/vaultspec_rag/config/_schema.py`
- `S03` `M` `src/vaultspec_rag/config/_settings.py`
- `S03` `M` `src/vaultspec_rag/tests/test_gpu_profile_harness.py`
- `S03` `M` `src/vaultspec_rag/tests/test_encode_bucket_planner.py`
- `S03` `M` `src/vaultspec_rag/tests/test_config.py`
- `S03` `M` `docs/configuration.md`
- `S03` `M` `.vault/research/2026-09-30-pipeline-performance-research.md`
- `S03` `M` `.vault/audit/2026-09-30-pipeline-performance-audit.md`
- `S03` `verify:` `ruff check src dev tools` -> `pass`
- `S03` `verify:` `ruff format --check src dev tools` -> `pass`
- `S03` `verify:` `ty check --python sparseencode/.venv/Scripts/python.exe (eight changed Python files)` -> `pass`
- `S03` `verify:` `pytest focused planner/config/harness/AST/documentation/environment preflight (253 passes)` -> `pass`
- `S03` `verify:` `pytest final config/configuration_doc/env_settings_centralised (94 passes)` -> `pass`
- `S03` `verify:` `python -m dev.gpu_pipeline_profile encoder --output .pytest-tmp/pipeline-sparse-budget-passing-comparison --rounds 3 --warmups 2 --items 32 --sparse-budgets 8192,24000 --sparse-budget-seconds 30 --budget-comparison-only --skip-trace --py-spy C:/Users/hello/.local/bin/py-spy.exe --seconds 30 --gil` -> `pass`
- `S03` `verify:` `explicit restored energy/recovery/parity/argument/native/teardown guard mutation proofs` -> `pass`
- `S03` `verify:` `mdformat --check docs/configuration.md and five feature records` -> `pass`
- `S03` `verify:` `vaultspec-core vault check all --feature pipeline-performance --json` -> `pass`
- `S03` `verify:` `verify-final-resident.py exact-spec retry children succeeded and service admissions open` -> `pass`
- `S03` `verify:` `three-arm sparse comparison including4096 strict document-weight parity` -> `fail`
- `S03` `by:` `root with GPT-6.1 Sol encoder, harness and independent review agents`
- `S03` `verify:` `verify-final-selection.py final selected comparison/default and rejected-arm barrier` -> `pass`
- `S04` `M` `.vault/audit/2026-09-30-pipeline-performance-audit.md`
- `S04` `M` `.vault/plan/2026-09-30-pipeline-performance-plan.md`
- `S04` `verify:` `independent GPT-6.1 Sol integrated review b9d2daf0 through66c8b9c0` -> `pass`
- `S04` `verify:` `applicable full Ruff/format/eight-file type/253 preflight plus94 final affected tests` -> `pass`
- `S04` `verify:` `24 paired windows strict parity source stability CUDA trace nonblocking stack evidence and exact-spec service restoration` -> `pass`
- `S04` `verify:` `vaultspec-core vault check all --feature pipeline-performance --json` -> `pass`
- `S04` `verify:` `mdformat --check docs/configuration.md and five feature records` -> `pass`
- `S04` `by:` `root and independent GPT-6.1 Sol reviewer`
- `S04` `M` `.vault/index/pipeline-performance.index.md`
- `S04` `verify:` `final feature status all four Steps checked and latest verification pass` -> `pass`
- `S04` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S04` `verify:` `Ruff lint and917-file format plus focused ty` -> `pass`
- `S04` `verify:` `pytest test_substitution_discipline and test_gpu_profile_harness52` -> `pass`
- `S04` `verify:` `substitution allowance17-to16 intended guard failure restored2guard passes` -> `pass`
- `S04` `verify:` `independent GPT-6.1 Sol scoped publication policy review` -> `pass`
- `S04` `by:` `root with GPT-6.1 Sol harness executor and independent reviewer`

## Notes

- `S01` An externally owned merge into this worktree delays the explicit-path Step commit. No foreign staged files were modified or included. Native execution is deferred until the reviewed pins are committed.
- `S01` Explicit-path commit and native execution remain deferred until the externally owned merge is finished. Overall review is PENDING for real native/CUDA evidence.
- `S02` Partial Step only: CUDA/native inference measurements and sparse budget/parity selection remain blocked by active service tickets and pending external merge. S02 stays unchecked; no sparse batch/precision/backend default changed.
- `S01` Execution moved to isolated feature/pipeline-performance worktree at b9d2daf0 so the externally owned sparseencode merge can proceed. Shared GPU admission remains enforced; copied earlier CPU evidence retains its original corpus hashes.
- `S01` S01 corrective reopen closes live profiler suspension hazard. Same resident service recovered without restart or job cancellation. CUDA and sustained energy remain pending; failed profiler attempts excluded.
- `S02` Sequencing separates completed AST work from required GPU and sustained-energy selection now in S03. Conditional repeat timing interval includes no gain. No indexing throughput or energy improvement claim.
- `S03` 4096 experiment rejected before energy windows; default remains24000 because8192 short energy regressed.8192 is opt-in long/mixed tuning. Both owned cancellations have exact-spec succeeded retry children; first HTTP timeout reconciled against created-child records.
- `S03` The recorded failed three-arm experiment is preserved as history; it did not evaluate the shipped selection. Final verification explicitly proves the selected two-arm comparison and unchanged 24000 default pass, and the rejected 4096 arm aborted before windows.
- `S03` A supplementary verification helper initially imported `get_config` from the namespace instead of `config._settings.` The import was corrected and the exact helper rerun passed before checkpoint. The premature helper pass entry is validated by that completed run; production gates were unaffected.
- `S04` S04 reopened when broader publication checks found the missing reviewed unit-boundary declaration. The exact seventeen-site declaration retains existing guard logic and was bounded/mutation-proven; production and measurement behavior remain unchanged.
