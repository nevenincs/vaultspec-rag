---
tags:
  - '#audit'
  - '#open-issues-closeout'
date: '2026-09-27'
modified: '2026-09-27'
body_schema: 'body-v2'
body_hash: 'sha256:a024fbd7aa1c7490525a1640acd3007e1ebc44cd8791429d4c762eb9ade30093'
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

## Recommendations

Local integrated review: **PASS**, no unresolved high or critical finding. Preserve the failed original campaign and authorized follow-ups. Keep the existing test contracts and bounds. Required PR CI and gated historical release promotion remain external completion conditions; do not equate local green with release promotion or mark the release disagreement repaired before its archive/acquisition gates pass.
