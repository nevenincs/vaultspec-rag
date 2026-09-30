---
tags:
  - '#audit'
  - '#sparseencode'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:a1fb7d92a3b477980a68ef714c8126e48536a9b9ce706a47e6b9700d86c04bb0'
related:
  - "[[2026-09-30-sparseencode-plan]]"
  - "[[2026-09-30-sparseencode-adr]]"
---

# `sparseencode` audit: `Integrated breaking sparse upgrade review`

## Scope

The review covers the integrated S01 implementation and S03 reconciliation under `2026-09-30-sparseencode-plan`, from base `3311ccdfb4bb5c3d1ef825f799c36f788a9d0c31` through S01 commit `056d7f27` and the stable completed S03 working tree. The independent reviewer is a GPT-6.1 Sol subagent; the supervisor owns shared gates, GPU borrowing and serialized Step commits. Governing decisions are the accepted sparseencode ruling, storage identity/conformance, single GPU ownership and batch adaptivity. Reviewed interfaces include configuration, pinned acquisition/cache readiness, inference locks and ordering, model mismatch refusal/rebuild recovery, release metadata, CI, operator migration guidance and authorized historical reference removal.

Final review status: PASS on 2026-09-30. Both Steps are checked and have passing ledger evidence. No unresolved material finding remains. The final review reuses applicable code analysis and verification; it launches no duplicate shared check.

## Findings

### rebuild-recovery | high | Sparse mismatch refusal must reach existing rebuild recovery

Resolved before checkpoint. A newly independent error type would bypass vault/document indexer catches for the established storage compatibility superclass. `StorageModelError` now subclasses `StorageGeometryError`; the distinct sparse mismatch verdict still refuses ordinary reads/writes, and explicit rebuild can recover through existing paths. The reviewer traced vault, document and code rebuild routing, including code generation publication. Real local-store tests exercise typed refusal, administrative recovery, empty recreation and the conforming replacement stamp; they do not claim to invoke every full indexer end to end. Evidence: the 295-test supervisor selection includes `test_storage_identity.py`, and the refusal guard's mutation failed with DID NOT RAISE before its restored pass.

### cache-readiness | high | Sparse readiness must require the reviewed complete revision

Resolved before checkpoint. The old readiness probe accepted an unpinned config-only cache entry while inference required the reviewed remote implementation and complete weights. Readiness, provisioning, warmup and test setup now share the offline full-snapshot probe; the sparse default resolves its pinned revision and required code/tokenizer/safetensors files. Readiness remains torch-free. Focused readiness tests, a fresh subprocess import check and the supervisor selection passed. Cache completeness and safetensors/pin guards were mutation-proved and restored.

### maintained-surfaces | low | Release and governing prose must match the implemented adapter

Resolved before checkpoint. The batching ADR now permits the scoped adapter that delegates pinned upstream semantics; dense library encoding remains authoritative. Operability no longer promises an unimplemented custom failure envelope. Configuration fallbacks, final-vector top-k wording, readiness/cache descriptions and guard-proof prose match code. Two empty workflow environment mappings left by acquisition removal were removed; actionlint and nine CI hardware guards passed.

### final-verification | low | Completed scope passes with explicit hardware and compatibility limits

The reviewer independently returned PASS for `3311ccdf..056d7f27` plus completed S03 records. The adapter delegates pinned upstream semantics, prepares/converts on CPU outside the forward lock and restores document order. Sparse incompatibility refuses scoring/writes and exposes rebuild recovery, while dense mismatch and unknown-identity policies retain their governing behavior. The release wheel and source distribution are version 0.6.0 and include the adapter/profile/cache modules and declared GPU dependency floors. Retired acquisition/model reference sweeps are clean in the working tree and release wheel.

Supervisor verification: `just check-python` (914 files formatted), `just check-type`, `just check-type-strict` (zero errors/warnings), `just check-toml`, `just check-workflow`, `just check-docs-version`, `just check-docs-conventions`, `just check-markdown`, feature vault conformance (zero errors/warnings), plan check (no findings) and `just build-python` all passed. The source selection command began `.venv/Scripts/python.exe -m pytest` and selected package tests `test_model_setup.py`, `test_encode_bucket_planner.py`, `test_adr_regression.py`, `test_provision.py`, `test_env_credentials.py`, `test_env_registry.py`, `test_cli_warmup.py`, `test_hook_sandbox.py`, `test_install_client_role.py`, `test_install_torch_config.py`, `test_gpu_session_lock.py`, `test_storage_identity.py`, `test_readiness.py`, `test_dev_aggregators.py`, `test_substitution_discipline.py` and `dev/guards/test_ci_hardware_tiers.py`; 295 passed in 327.59 seconds. Local evidence is in `.pytest-tmp/sparse-final-tests.log` and `.pytest-tmp/sparse-final-events.jsonl`. Worker checks add 174 surface tests, 120 encoder/model/storage tests and 17 final maintenance/readiness tests; applicable evidence is reused rather than summed as unique tests. Four encoder, five surface and three development guard mutation proofs failed on the intended assertion, then passed after restoration; source docstrings retain that evidence.

Three borrowed-CUDA tests passed in 61.86 seconds for pinned upstream query/document parity, single/batched representation and bounded output retention. The documented paired RTX 4080 SUPER benchmark measured 1.2784x throughput on 32 mixed-length documents, batch size four, float32/SDPA and seven alternating measurement pairs after two warmup pairs. Baseline/new medians were 0.500361/0.391393 seconds (63.95/81.76 documents per second). Both peaked at 3163.60 MiB total allocated CUDA memory. The research record includes corpus construction, methods and all timings. This establishes neither memory reduction nor retrieval-quality improvement; Apple MPS and minimum dependency-floor versions were not tested. GPU checks used the newer installed stack documented in the research.

Resident service PID 60756 resumed its running quiescence state with models loaded after GPU borrowing. Its health endpoint reports a latest indexing job failure with generic reason `other`; this operational observation is not treated as inference verification. Development did not restart the daemon or request a live-index rebuild. Existing unrelated historical plans still account for 38 execution-ledger warnings in the project-wide vault check; the sparseencode feature is clean.

## Recommendations

Retain float32/SDPA at the measured revision. Rebuild sparse indexes explicitly after installing version 0.6.0. Re-review upstream Python implementation and representation compatibility before changing the pinned revision. The benchmark establishes only the measured mixed-length CUDA batching improvement; it does not establish Apple MPS support, retrieval-quality equivalence with the retired model, or lower peak memory.
