---
tags:
  - '#plan'
  - '#review-findings'
date: '2026-09-27'
tier: L1
related:
  - '[[2026-07-23-service-orphan-reaping-adr]]'
  - '[[2026-09-23-vault-result-evidence-adr]]'
  - '[[2026-04-05-service-lifecycle-tests-adr]]'
modified: '2026-09-27'
body_schema: body-v2
body_hash: 'sha256:cd1761d01cea967100e2fdfebbfcfe395900762dc350f7d0e9cc73fb2ad28150'
---

# `review-findings` plan

## Description

Approved 2026-09-27

The user explicitly requested fixing every finding from the individual test review while retaining the tests. Repair zombie-aware termination and preserve owned-child cleanup time; strengthen active-index concurrency proof, ecosystem command success and lifecycle assertions, and evidence-span presence. Resolve class-fixture and JUnit-property warnings. Existing accepted orphan-reaping, lifecycle-test isolation and vault-evidence decisions govern. No dependency, persisted schema, or public interface change is required. PR 552 has already merged; prepare a separate branch without touching other sessions' work. Preserve previous campaign evidence and run focused covering validation with fresh timings.

## Steps

- [x] `S01` - Repair termination and strengthen reviewed regression guards with audited covering validation; `src/vaultspec_rag/_process_probe.py, src/vaultspec_rag/cli/_process.py, src/vaultspec_rag/cli/_service_stop.py, src/vaultspec_rag/tests/test_service_stop_port.py, src/vaultspec_rag/tests/test_process_termination.py, src/vaultspec_rag/tests/integration/test_server_index_concurrency.py, src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py, src/vaultspec_rag/tests/integration/test_ecosystem_integration.py, src/vaultspec_rag/tests/integration/test_vault_evidence_gate.py, .vault/audit/, .vault/exec/, .vault/index/`.

## Parallelization

Execute serially in the isolated review-findings worktree.

## Verification

Run explicit lint, format and type gates and covering CPU and GPU integration tests after the repairs. Prove regression guards fail on their named mutations and pass after immediate restoration. Record commands, exit codes, timings and resource/benchmark evidence separately from the original campaign. Review integrated behavior and retain all tests and existing safety thresholds.
