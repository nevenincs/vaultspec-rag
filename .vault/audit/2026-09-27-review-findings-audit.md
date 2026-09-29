---
tags:
  - '#audit'
  - '#review-findings'
date: '2026-09-27'
modified: '2026-09-27'
body_schema: 'body-v2'
body_hash: 'sha256:84d61eef5e423536dec6dc9a99397791495a613f3206f5a6bd030b3b47f14c53'
related:
  - "[[2026-09-27-review-findings-plan]]"
---

# `review-findings` audit: `termination and regression evidence`

## Scope

Review the cohesive fixes authorized on 2026-09-27 after the individual test review. Retain every existing test, repair the four medium findings, resolve the two warning sources, and audit fresh covering validation after its green signal. Accepted orphan-reaping, service-lifecycle test isolation and vault-result evidence decisions cover the work. No new architecture commitment or acceptance-floor change is required. Work is isolated on `fix/review-findings`, based on `4981478e`; PR 552 had already merged before this follow-up.

## Findings

### zombie-confirmation | medium | Resolved: non-child zombies no longer spend the exit budget

`src/vaultspec_rag/_process_probe.py:431` owns the termination predicate, and `src/vaultspec_rag/_process_probe.py:901` owns bounded exit waiting and child reaping. CLI termination, post-termination confirmation, orphan outcomes and their tests now use those implementations. The duplicate CLI wait and termination predicates were removed. A confirmed zombie is exited; an unreadable possible survivor remains protected. The existing signature, lock/pointer protection, permission-refusal outcomes and owned-Qdrant identity validation remain intact.

The new pure policy tests distinguish a non-child zombie from a surviving process and verify the original owned-child cleanup deadline remains available. On the final test source, removing zombie recognition failed at the forbidden-wait assertion; treating every PID as exited failed the survivor refusal assertion; immediate restoration passed both. The real orphan protection cases passed in 3.784, 3.903 and 3.963 seconds on Windows. The reviewed historical Linux delay motivated the repair, but this run supplies no new native Linux latency measurement and makes no cross-platform speedup claim.

### index-search-overlap | medium | Resolved: searches require completed index model work

`src/vaultspec_rag/tests/integration/test_server_index_concurrency.py:101` observes the real progress reporter's completed-forward callback. Search admission requires that event, a positive completed-forward count and an unfinished index. The benchmark helper accepts this reporter while preserving its default reporter for other callers. The test still requires nonempty results, search completion before the index finishes, exact chunk cardinality and the existing CUDA headroom floor and tolerance.

The single admitted benchmark indexed 256 files and 768 chunks in 24.146148 seconds. One index forward completed before search admission; all eight searches returned nonempty results and completed before indexing finished. Peak native CUDA allocation was 2652.286622 MiB, peak reservation 2902 MiB, and observed reserved headroom 13473.375 MiB against a required 3275.075 MiB with the unchanged 128 MiB tolerance. Sampled process RSS rose from 2144.777344 to 2474.218750 MiB. The pytest body took 26.72 seconds; pytest took 59.60 seconds; the monitored driver took 63.216027 seconds. These are different boundaries, not interchangeable measurements.

### ecosystem-command-success | medium | Resolved: failed core commands cannot reuse a seeded fixture

`src/vaultspec_rag/tests/integration/test_ecosystem_integration.py:76` requires successful subprocess exit for every install, sync, ownership re-anchor, uninstall and reinstall command. The lifecycle fixture creates a real core-managed research record and compares its exact bytes after uninstall and again after reinstall. Existing provider, MCP enrollment, CRUD and idempotence assertions remain. Removing subprocess success checking failed the real invalid-command refusal test with `DID NOT RAISE`; restoring it passed. All ecosystem cases passed against the installed core CLI.

### evidence-span-presence | medium | Resolved: a completely absent span witness cannot pass

`src/vaultspec_rag/tests/integration/test_vault_evidence_gate.py:166` requires at least one usable span before accepting an empty offender list. Every present span must still cover exactly its snippet. Optional absent spans on individual hits remain permitted; ranking floors were not changed. Removing all spans from the observed input failed the exact gate method at its named absence assertion; restoring the witness passed. That mutation proof uses an observed-record input without replacing a live integration component. Separately, the real frozen-corpus experiment passed all six evidence tests, including four parametrized metric checks, across 36 labeled queries and 357 present spans.

### pytest-reporting | low | Resolved: fixture and JUnit compatibility warnings removed

The three class-scoped ecosystem fixtures are module functions, preserving their names and sharing boundaries while avoiding instance-bound fixture deprecation. Evidence metrics use four uniquely named suite properties compatible with xunit2. The final integration XML contains all four metric summaries, and the integration log contains neither reviewed compatibility warning. The expensive frozen-corpus setup remains session-shared; its 130.28-second setup phase was recorded rather than hidden or duplicated.

### validation-integrity | low | PASS: timings and source identities audited after green

Fresh covering selections passed 215 unique test cases with three existing platform-specific skips. All existing test functions in modified test modules were retained, verified by comparing their qualified AST names against the base commit. The final three unit probes were rerun after strict typing corrections. Production and integration test source stayed identical across both monitored live correctness lanes; only the new unit-probe declarations changed afterward. The benchmark's source digest was unchanged before and after execution: `560ea69b412488c3a298fee78e4c46089c40cbd9cd9d8877604a306458525983`.

| Selection                            | Passed / skipped | JUnit suite seconds | Test phase sum seconds |
| ------------------------------------ | ---------------- | ------------------- | ---------------------- |
| Process safety                       | 59 / 3           | 25.810              | 24.889961              |
| Process contracts                    | 115 / 0          | 116.516             | 113.430657             |
| Benchmark harness                    | 5 / 0            | 1.875               | 0.522051               |
| Final unit probes, repeated subset   | 3 / 0            | 0.312               | 0.068693               |
| Ecosystem, evidence and Qdrant child | 33 / 0           | 210.161             | 181.020901             |
| Real service termination             | 2 / 0            | 95.909              | 74.856005              |
| Search headroom                      | 1 / 0            | 59.595              | 41.365761              |

Suite totals include collection and lifecycle work outside individual setup/call/teardown reports. The live integration and subprocess drivers took 219.961463 and 99.440614 seconds, with sampled process-tree RSS peaks of 3145351168 and 3909861376 bytes. The benchmark driver sampled 3038277632 bytes across its process tree; that scope differs from the indexer's own RSS sample.

Two quiet-host admission attempts refused execution before pytest launched. The admitted run's three host CPU samples were 16.0%, 17.3% and 16.8%, under the unchanged 20% ceiling. Exactly one benchmark test execution occurred, with no retry. All 53 processes suspended for that admitted run were resumed with incarnation checks. Refused admissions also ran their restoration paths. No benchmark distribution or statistical speedup is claimed from one observation.

Raw report logs, JUnit, per-phase CSV, resource samples, benchmark JSON, final fail/restore/pass proofs and SHA-256 manifests are preserved separately from the previous campaign under `tmp/open-issues-evidence/review-findings-*`. The post-green audit is `review-findings-timing-audit.json`; its per-test table is `review-findings-test-timings.csv`. The initial full lint run exposed 15 unknown parameter-type errors in the new unit probes and an unfinished audit scaffold. Both were repaired; none was suppressed. The execution ledger records the final explicit gate results. The duplication scan found zero clones.

### child-exit-acknowledgment | low | Resolved: preserve the successful POSIX child-reap proof

After the preceding post-green review, the integrated safety pass found that consolidating the CLI wait also needed to preserve its successful `waitpid` acknowledgment. `src/vaultspec_rag/_process_probe.py:884` now returns whether it reaped the requested child, and the central wait returns immediately on that proof. This preserves the previous CLI behavior without looking up a PID that could already belong to a new process. Other callers may continue ignoring the acknowledgment. The direct-child and reused-PID policy cases are pure unit tests; they do not replace live components.

Removing the acknowledgment from the wait failed at `confirmed child exit must not inspect a reused PID`; discarding the native wait acknowledgment failed the direct-child assertion. Immediate restoration passed both, and the zombie, survivor, command-refusal and missing-span mutation proofs passed again on the final source. The final covering process selection passed 70 tests with the same three platform skips: JUnit 22.912 seconds and phase sum 21.983604 seconds. The two real service-stop cases passed again: JUnit 112.672 seconds, phase sum 87.799534 seconds, driver wall 117.921653 seconds and peak sampled tree RSS 3917254656 bytes. Its source digest was stable at `94951ce12c1dc8231d795e86bc2486af21ab9a741fde64a50d5d147882a13a1a`.

The final post-green audit counts 217 unique passed cases and three unchanged platform skips. The earlier 215-case entry and its measurements remain the preceding review snapshot. The source manifest now identifies exactly two files changed after the first live correctness lanes: the process probe and its new unit tests. Both received final covering verification. Benchmark, index, search, evidence and ecosystem test source remained identical; the headroom benchmark was not repeated. Both refused admission records were also audited: neither launched pytest, and every suspended process was resumed. Final mutation evidence is `review-findings-final2-guard-proofs.json`.

### final-static-gates | low | PASS: all explicit source and documentation targets

The final `python -m dev lint all` completed with exit 0 across all 16 targets, including package style/format, both type profiles, imports, production complexity, nesting, size, workflow and documentation gates. The final duplication audit completed with exit 0 and found zero clones. Earlier intermediate formatter failures were repaired through the owning vault verbs and re-attestation; the final modified-stamp check is clean. The global vault check reports 38 pre-existing historical ledger warnings and no errors. No checks were skipped or relaxed, and unrelated historical records were not rewritten.

## Recommendations

Behavioral review result: PASS, with no unresolved critical, high or medium finding. Keep all tests and the shared quality fixture. Retain the single-run benchmark as observation evidence, without promoting it to a performance baseline. Stop at the authorized local follow-up commit: the original single PR is already merged, and publishing another PR requires the user's direction.
