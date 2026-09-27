---
tags:
  - '#audit'
  - '#open-issues-closeout'
date: '2026-09-27'
modified: '2026-09-27'
body_schema: 'body-v2'
body_hash: 'sha256:f5f21a59ddcccfffe63b7815981e40b6e10701ccb662351b265a8c9f45bf8470'
related:
  - '[[2026-09-27-open-issues-closeout-plan]]'
---

# `open-issues-closeout` audit: issue corrections and measured local verification

## Scope

Review issues #546, #532 and #519 against the accepted decisions linked from the plan, merged corrections in #548 and this follow-up. This post-green review covers the complete native Windows CPU/CUDA/subprocess selection, five funded provider requests, the authorized targeted repairs and the quiet-host performance lane. Preserve the original failed campaign and all subsequent attempts separately. No production source changed after the original campaign; three test fixtures were corrected against existing production contracts. Historical release repair and required PR CI are tracked separately until their external gates finish.

## Findings

### package-checksums | medium | Duplicate wheel entries could satisfy the old two-line upload check

The package-index step in `.github/workflows/publish.yml:380` previously counted two selected manifest lines without proving each package appeared once. The follow-up now requires exactly one wheel and one sdist entry before digest verification. Removing both uniqueness conditions failed the exact-entry guard, and the restored workflow passed it.

### docs-command | low | The repaired troubleshooting command now has executable regression coverage

`docs/automatic-convergence.md:182` already carries the corrected bash fence and automatic-update filter from #548. The follow-up test reads that actual block and drives the jobs command through the real CLI to a loopback HTTP server. Restoring the removed flag failed the exit assertion; restoring the text fence failed the fence assertion. Both passed immediately after restoration.

### content-recovery | low | Request-scoped refusal remains distinct from credential rejection

`src/vaultspec_rag/search/_typesafe_transport.py:344` already recognizes non-authentication 403 responses and keeps subsequent requests admitted. The follow-up normalizes edge-sensitive punctuation recursively in state values without altering keys, question contracts or caller evidence. Removing normalization failed received-state equality and passed after restoration.

### offline-verification | low | Focused checks pass before the live campaign

All 101 focused unit and loopback tests passed in 19.34 seconds. Raw report logs and JUnit XML are in `tmp/open-issues-evidence/offline-regressions.jsonl` and `tmp/open-issues-evidence/offline-regressions.xml`. Four mutation fail/restore/pass sequences are in `tmp/open-issues-evidence/mutations.json`. Python lint and format, repository-wide ty and configured basedpyright, actionlint and the workflow recipe contract pass. An additional basedpyright invocation explicitly including release-tool tests reported 43 existing typing errors outside its configured package scope; ty covers those files and passes.

### fixture-contracts | low | Four failing tests now exercise the existing contracts

The progress test requires the hash-documents phase and asserts all documents advance. The two stamp-refresh fixtures start with a modified stamp: adding a new line changes citation metadata and cannot prove a stamp-only refresh is free. The performance fixture creates a one-file full publication through declared discovery excludes before incremental indexing; production correctly refuses incremental indexing into an unpublished store. All original strict work, proof, concurrent-search and CUDA-headroom assertions remain. Three targeted GPU tests pass; the corrected stress test passes separately. No failure was converted to a skip and no production guard was bypassed.

### live-outcomes | low | Final native selection is green after authorized fixture repairs

The original campaign at `fca45b28098626ccde4590e67d4418832ecea734` remains recorded as failed: 6,228 passed, three failed and six skipped in 2,886.295 seconds. Its performance preflight declined a busy host. After the user's expanded authorization, three targeted GPU tests passed; the full performance selection had 13 passed and one fixture failure, followed by a successful single-test repair verification. Folding only the latest outcome for each distinct node gives **6,245 passed, six skipped, zero unresolved failures**. This is combined verification evidence, not a claim that the original single campaign passed. Each invocation captured source digests unchanged during execution. The final tested source digest is `2153aa2b7cce0ef6b41675849e6d635e71a8a0cb49ead093e8d207ec360ae6db`.

| Invocation            | Passed / failed | Driver wall (s) | Peak sampled tree RSS (GiB) | Median call (s) | Call p95 (s) | Longest call (s) |
| --------------------- | --------------- | --------------- | --------------------------- | --------------- | ------------ | ---------------- |
| CPU, xdist            | 5431 / 0        | 149.347         | 12.494                      | 0.0035          | 1.0563       | 28.2606          |
| CUDA/integration      | 722 / 3         | 1163.230        | 4.962                       | 0.2396          | 5.6541       | 62.8401          |
| GPU subprocesses      | 75 / 0          | 1565.511        | 6.309                       | 2.9700          | 68.6841      | 71.2621          |
| Three repaired tests  | 3 / 0           | 31.798          | 2.081                       | 0.6144          | 1.4102       | 1.4102           |
| Performance selection | 13 / 1          | 92.522          | 3.937                       | 0.1686          | 36.4407      | 36.4407          |
| Repaired stress test  | 1 / 0           | 49.593          | 3.042                       | 16.6825         | 16.6825      | 16.6825          |

### timing-method | low | Timing evidence is descriptive and includes collection overhead

Wall times use `perf_counter` around the child invocation and include process startup and resource collection. Per-test setup/call/teardown durations come from pytest report logs; parallel phase sums exceed CPU lane wall time. The CPU phase sums are 14.136/1,114.302/27.479 seconds; CUDA 193.179/923.821/13.591; subprocess 234.741/1,283.092/19.641. Call p95 is the nearest rank over heterogeneous tests, not a repeated-workload latency claim. No before/after speedup is inferred from these different invocations or host conditions.

The sampler requested 100 ms intervals; observed medians were 120Ã¢â‚¬â€œ134 ms, and the largest gap was 1.429 seconds in the subprocess lane. Peaks are sampled aggregate RSS over the child process tree, may miss short spikes, and may count shared pages more than once. They exclude external processes and the idle resident daemon. The borrower protocol quiesces the daemon and grants an exclusive GPU lease to pytest; the real models are in the measured pytest tree. These RSS figures are not host physical RAM totals or CUDA allocation measurements.

The three-test repair recorder mislabeled its completion timestamp as `started_utc`. The raw file is preserved. Its log creation was 09:04:39.196458 UTC, recording completed at 09:05:10.995103 UTC, and the valid monotonic wall time is 31.798297 seconds. The audit explicitly marks that timestamp as recorded-at rather than using it as the start. The final performance recorder captures start and finish correctly.

### slow-tests | low | The longest calls are lifecycle and resource acceptance tests

CPU's longest call is the captured GPU borrower target test (28.261 seconds); two citation-gate tests take 19.972 and 19.537 seconds. CUDA's longest calls are managed code pause/resume (62.840), large-corpus pause/resume/cancel (41.830), and managed vault pause/resume (35.776). Subprocess discovery recovery and heartbeat self-healing take 71.262 and 70.675 seconds, followed by idle-TTL eviction at 69.385 seconds. The performance corpus-doubling high-water test takes 36.441 seconds. These tests exercise real subprocess, model, heartbeat and idle lifetime behavior; this run gives no evidence that their waits should be weakened. Full top-ten calls and module phase sums remain in `tmp/open-issues-evidence/audit-analysis.json`.

### performance-headroom | low | Quiet-host workload passes with real concurrent results

The complete performance selection admitted CPU samples 13.5%, 16.0%, 11.2%. The corrected stress check admitted 13.1%, 14.3%, 14.7% and indexed 256 files/768 chunks in 14.854966 seconds; all eight searches returned results before indexing finished. Baseline/peak RSS were 2,148.027/2,473.441 MiB, CUDA allocated 2,449.306/2,646.916 MiB and reserved 2,458/2,902 MiB. Observed reserved headroom was 13,473.375 MiB against 3,275.075 MiB required (128 MiB tolerance). The benchmark details come from the existing workload harness, not the process-tree sampler.

Temporary suspension/resumption counts were 73/73 for the full performance lane and 34/34 for the repaired stress check, verified by PID and creation identity with `finally` restoration. Two additional preflight-only attempts started no pytest process and resumed all 34 and 39 suspended processes. Busy preflights are unavailable measurements, not failed tests. The original CPU and GPU lanes ran under contention and are descriptive timings only.

### skips-platforms | low | Six native skips are accounted for and MPS is unavailable

Four skips require POSIX reparenting, file-lock or signalling semantics. One verifies rejection of Windows icon stamping on a non-Windows host. The sixth needs an unopenable Windows PID 4; PID 4 was openable in this session. No new skips were introduced. Linux CI is needed for the POSIX and non-Windows paths; the access-denied OS branch depends on host permissions. This Windows CUDA host cannot prove native MPS behavior. Do not report every supported hardware platform tested.

### hosted-provider | low | Five funded requests succeed without poisoning enrollment

Distinct benign-before, quoted-command, sensitive-path, traversal-path and benign-after probes each made one real request and finished with enrollment active: 311.454, 236.441, 323.519, 211.883 and 242.150 ms. The first opened a connection; subsequent requests reused it. These successful probes do not reproduce a live Cloudflare 403. The real loopback HTTP regressions and mutation proof establish the content-403 recovery branch independently. No key value is stored in the audit.

### static-audits | low | Configured gates pass; advisory findings remain explicit

All 16 configured lint targets passed, including Python lint/format, ty, configured basedpyright (zero errors/warnings), workflow/actionlint, absolute imports, complexity, nesting, size and documentation/vault checks. Python lint/format, ty and basedpyright passed again after the final fixture correction. Dependency advisory verification covered 157 Python coordinates and one binary with no unaccepted advisory; deptry inspected 309 files with no issues. Bandit reported 41 low and 30 medium findings, zero high, outside the changed files; these are advisory existing patterns. Vulture reported the existing abstract `ReentrantLock.acquire` blocking parameter in `_store_locks.py:46`. The broad vault check had 38 historical completed-plan ledger warnings plus this plan's stale body hash; own-feature CLI reconciliation addresses the latter without changing historical plans.

The other session owns the five `just` audit/complexity/nesting/health command implementations. This session consumes existing checks and does not modify those commands. Duplication and test complexity reports are supplementary advisory evidence and their exit code alone is not a clean finding verdict.

### resident-restoration | low | The installed compatible service is restored

After GPU verification, the temporary checkout 0.5.2 service was stopped and the installed 0.4.35 service restarted through its explicit global shim with default automatic updates. Redacted status proves it is ready, PID identity matches, models/reranker are loaded, CUDA is available and no degraded reasons are reported. This restores compatibility with installed clients. Historical persisted failed jobs are not new failures from this restart.

### evidence-integrity | low | Raw attempts remain separate and are hashed

`tmp/open-issues-evidence/audit-analysis.json` preserves original and latest outcomes, per-lane phase sums, all skip reasons, top-ten calls/modules, actual sampling intervals, CPU samples, timestamp correction and an SHA256/byte index of raw report logs, JUnit XML, resource samples and benchmark reports. The scripts and raw logs remain local ignored evidence. The following hashes anchor the principal reports:

- `live-campaign/summary.json`: `273a8d5fe7ab14e375dd17e8197614ec17e2c9bba52feec56bdf211406bb91b3`.
- `repair-verification/result.json`: `6b635c527acc5913cb82ed0d12be9b853c668a19b463b3a2db630042e7cc3169`.
- `performance-verification-02/result.json`: `25f158819663aea6dfef856479e6cd8c01cf47b964a719318161c60503515276`.
- `performance-verification-04/result.json`: `d550dfc291d9dc743f3dcbe50e9a836ee6dbfd0200414183580f1be1d5f92171`.
- `audit-analysis.json`: `94870b1360eb4fe3fd7a52de8707f20c10a2d031e1a21dce26d82a2dee511a12`.

### supplementary-audits | low | Existing advisory reports identify no changed-file finding

The duplication report scanned 705 files and found eight existing test clones (187 lines, 0.08%). None intersects this PR's changed files. The cognitive test-tree audit found no function above 20; the cyclomatic advisory reported the existing rank-D shared-readiness test in `test_service_search_diagnostics_reporting.py:79`, outside this diff. These findings remain visible and are not a claim that the repository has zero duplication or advisory complexity findings.

### ci-size-followup | medium | Final fixture addition crossed the module limit after the earlier size gate

PR CI at `7307962d` passed Windows and both Linux correctness jobs plus dependency advisories, but pylint rejected the stress test module at 1506 lines against the unchanged 1500-line bound. The prior local size check preceded the final fixture addition. This verification gap is corrected by the subsequent cleanup's behavior-based concurrency split and the passing final size gate. The original failure is preserved. The isolated duplicate headroom extraction is excluded from the PR.

### combined-preservation | low | Issue regressions survive the completed cleanup

The user explicitly authorized including the completed code-health cleanup in this same PR. Its structural findings and review remain in `2026-09-27-code-health-cleanup-audit`. Final verification uses the committed implementation `6395caeb` and its later metadata-only review `2503c0de`; the source digest is `ce47dac5c6b7be9073a001c5b8ad1e3ddec975377eb0612599378c57e9ae0f72`. AST comparison proves `_model_state`, `_payload`, `_check_status`, the complete headroom class and its integration marker unchanged from `7307962d`. The full combined campaign exercises the moved headroom class at its new owner. No duplicate extraction or compatibility shim is included.

### combined-live-campaign | low | The final settled campaign is green without retries

The final complete campaign reports 6245 unique passed tests, 6 existing platform skips and zero failures. All four test lanes exit zero. The raw campaign integrity guard remains red because an unrelated session edited workflow/CI-contract files after the CPU lane. `combined-source-reconciliation.json` establishes the subsequent green signal: every scoped Git blob in this isolated PR checkout matches the campaign initial committed source; live runtime files never changed. Checkout byte hashes differ under Git line-ending conversion. No raw result is overwritten; automatic retries and further live reruns are zero. End-to-end campaign wall time is 2802.884834 seconds, including preflights, lane startup, resource sampling and hosted probes. Original failed attempts and prior authorized repairs remain separate.

| Lane       | Passed | Skipped | Pytest seconds | Driver seconds | Peak sampled RSS MiB |
| ---------- | -----: | ------: | -------------: | -------------: | -------------------: |
| `python-1` |   5431 |       6 |         118.08 |     119.894825 |            12313.367 |
| `gpu-1`    |    725 |       0 |        1051.69 |    1059.545315 |             4958.805 |
| `gpu-2`    |     75 |       0 |        1510.67 |    1515.677725 |             6306.406 |
| `perf-1`   |     14 |       0 |          93.95 |      98.318205 |             4036.480 |

### combined-timing-audit | low | Timing and resource evidence was audited after the final green signal

`combined-audit-analysis.json` was generated only after asserting the reconciled green signal for the isolated PR scope. It rejects duplicate test execution and failed phases, hashes the raw artifacts and instrumentation, and writes `combined-live-campaign/test-timings.csv` with one row per test and separate setup/call/teardown seconds. Phase sums can exceed wall time in the parallel CPU lane. Median and p95 values describe heterogeneous cases; a single campaign establishes no speedup or confidence interval.

- `gpu-1.jsonl` setup/call/teardown sums: 176.500/842.955/9.752s. Longest calls: `src/vaultspec_rag/tests/integration/test_service_job_control_pause_restart.py::test_large_corpus_pause_resume_cancel_releases_and_converges` 39.279s; `src/vaultspec_rag/tests/integration/test_index_job_control_managed.py::test_managed_code_pause_releases_pipeline_and_resume_reconciles` 37.953s; `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py::test_watcher_converges_code_create_modify_rename_delete_and_active_edits` 26.501s.

- `gpu-2.jsonl` setup/call/teardown sums: 225.618/1243.848/20.127s. Longest calls: `src/vaultspec_rag/tests/integration/test_service_lifecycle_discovery.py::test_reconcile_recovers_discovery_without_touching_the_daemon` 73.675s; `src/vaultspec_rag/tests/integration/test_service_lifecycle_discovery.py::test_deleted_discovery_views_self_heal_on_the_next_heartbeat` 71.881s; `src/vaultspec_rag/tests/integration/test_storage_maintenance.py::test_maintenance_cycle_reclaims_only_time_confirmed_orphans` 68.413s.

- `performance\performance.jsonl` setup/call/teardown sums: 14.131/58.890/0.443s. Longest calls: `src/vaultspec_rag/tests/integration/test_indexer_integration.py::TestLargeCodeIndexHighWater::test_rss_and_cuda_high_water_remain_bounded_as_corpus_doubles` 33.823s; `src/vaultspec_rag/tests/integration/test_server_index_concurrency.py::TestLargeIndexSearchHeadroom::test_search_completes_while_large_index_retains_cuda_headroom` 15.579s; `src/vaultspec_rag/tests/integration/test_performance.py::TestPerformance::test_batch_query_latency` 3.478s.

- `python-1.jsonl` setup/call/teardown sums: 12.090/1037.877/25.650s. Longest calls: `src/vaultspec_rag/tests/test_gpu_borrow_captured_target.py::test_captured_target_uses_original_lease_after_singleton_paths_redirect` 23.013s; `src/vaultspec_rag/tests/test_citation_gate.py::test_the_checkout_carries_no_active_citation_or_identity_leak` 20.154s; `src/vaultspec_rag/tests/test_citation_gate.py::test_the_gates_own_file_is_exempt_from_path_literals_not_from_identity` 16.451s.

- `gpu-1-resources.json` actual sampler intervals: median 122.971ms, p95 138.244ms, maximum 224.255ms.

- `gpu-2-resources.json` actual sampler intervals: median 121.021ms, p95 127.539ms, maximum 151.149ms.

- `python-1-resources.json` actual sampler intervals: median 129.946ms, p95 142.880ms, maximum 165.060ms.

- `performance\resources.json` actual sampler intervals: median 119.103ms, p95 123.806ms, maximum 140.554ms.

Summed process-tree RSS can double-count shared pages and sampling can miss spikes; it is neither VRAM nor physical host usage. Device headroom is established by the performance test's own CUDA metrics and unchanged assertions. Correctness lanes ran under recorded contention; performance requires three CPU samples at or below 20 percent. Every temporarily suspended process is resumed with PID/creation identity verification: 33/33. The Windows host provides no native MPS proof. Successful funded hosted probes do not reproduce a real Cloudflare 403; the loopback HTTP and guard-mutation evidence establishes that branch.

### combined-static-audit | low | Configured gates pass and existing security findings are reconciled

All configured lint targets pass after vault-owned formatting repairs. The dependency advisory gate scans 157 Python coordinates and one binary without an unaccepted advisory; deptry finds no issue in 313 files. Bandit remains at 41 low, 30 medium and zero high findings. Comparing finding signatures across the completed refactor yields no new finding after the explicit owner-symbol migrations and the reviewed `_owners_for_points` key-argument extraction at `src/vaultspec_rag/indexer/_run_ledger_publication_receipts.py:521`. SQL text, placeholders and parameter values remain unchanged. The existing abstract lock parameter remains Vulture's sole report. These advisory findings are visible and are not asserted to be zero.

### combined-evidence-integrity | low | Final reports have durable digest anchors

- `combined-live-campaign/summary.json`: `7da6e79b2eeb17c0da4af9ace28a68c45356ce5f7319109b255a733255b04338`.
- `combined-live-campaign/test-timings.csv`: `03352b849bff562049067a3c7da76e971198d3dc30a56eddaac1493a66056be9`.
- `combined-audit-analysis.json`: `6fad576f73bfb87009e14dc8d61c8ccb05738531397d6881a745e9bfe393979b`.
- `combined-preservation.json`: `e196a81086cf453d21b0d56511798627bc9677a2c92ae2a2cbbeb044c823cbc0`.
- `combined-security-comparison.json`: `53c067f68c37cd8906daaa6850cadee635d1c2da7cdf205164cf71ccd75442fe`.

### combined-performance-evidence | low | Concurrent indexing and search retain measured CUDA headroom

The fixed 256-file/768-chunk corpus indexes in 14.912294s. All 8 searches return nonempty results; 8 complete before indexing. Peak process RSS is 2601.535MiB, peak CUDA allocated/reserved memory is 2671.787/2914.000MiB, and retained reserved headroom is 13461.375MiB against the unchanged 3275.075MiB requirement on a 16375.375MiB device. This is one controlled performance observation, with no repetition-based estimate.

Final funded hosted probe wall times: `benign-before` 313.889ms, 1 request(s), enrollment `active`; `quoted-command` 422.658ms, 1 request(s), enrollment `active`; `sensitive-path` 207.575ms, 1 request(s), enrollment `active`; `relative-traversal` 217.532ms, 1 request(s), enrollment `active`; `benign-after` 206.261ms, 1 request(s), enrollment `active`.

### final-source-and-service | low | Isolated scope and restored service are independently verified

The scoped Git-blob digest is `dfaf075b9ec244dc5e35d6452a05845d254f72f0510e96f188c98ed9915e0425` and matches every source blob from the campaign initial commit. The original campaign byte digests and false integrity result remain untouched. `combined-source-reconciliation.json` is anchored by SHA256 `8172a242dc5610d0506ddd672a2f81656d9cdcff300720eb1c0516a212ab5493`. The installed service was restored through its explicit global shim; redacted start/status reports confirm success and ready health. Separate runner-policy changes remain in the original worktree and are excluded from this PR.

## Recommendations

Final local integrated review: **PASS**, with no unresolved high or critical finding. Preserve all raw attempts and the settled source digest. Historical release repair must pass its archive/acquisition gates and latest-head PR CI must pass before completion is reported. Do not merge this PR from the author session.
