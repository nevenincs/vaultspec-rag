---
tags:
  - '#audit'
  - '#code-health-cleanup'
date: '2026-09-27'
modified: '2026-09-27'
body_schema: 'body-v2'
body_hash: 'sha256:5395a48bee9f3b88df4eecedc254a690c892e8b26d5610fd5b11035dd2c64414'
related:
  - "[[2026-09-27-code-health-cleanup-plan]]"
---
# `code-health-cleanup` audit: integrated maintainability remediation

## Scope

Review S01-S05 under the approved plan and accepted module-split, maintainability-remediation and incremental-publication-cost decisions. Verify direct ownership, preserved test cases, publication invariants, unchanged scanner thresholds and covering checks.

## Findings

### ownership-guard | low | Relocated publication owners remain guarded

The publication-finalization ownership registry now lists the proof and receipt owners. Mutation verification appended `FinalizationPhase.STALE_RECONCILED` to `_public_search.py`: the isolated ownership guard failed on its named canonical-owner assertion, then passed after byte-for-byte restoration in one uninterrupted sequence.

### substitution-guard | low | Test substitutions remain counted after decomposition

The existing interleaving substitution is registered at `_run_ledger_test_support.py`; CLI substitutions retain their original total of nine across the index and disk-preflight modules. Mutation verification added a textual `monkeypatch.setattr` site to the disk-preflight module: the isolated substitution guard failed on `substitution count grew`, then passed after byte-for-byte restoration in one uninterrupted sequence. No mutation remained on disk.

### integrated-review | low | PASS with no review findings

Independent Luna 6 review at max reasoning found no critical, high or low issues. The review traced direct publication ownership, mixin composition, point validation, preflight and checkpoint invariants, search and hosted classification, watcher state transitions, Qdrant validation and restore cleanup against the original code. Every original test identity remains; extracted assertions remain exercised. No shims, skips, suppressions or threshold relaxations were introduced.

### integrated-health | low | Reported structural and complexity findings are resolved

The original four modules above 1500 lines are below that limit. `tests/test_index_run_ledger.py` was 3837 lines; its nine independently collected owners are 163-608 lines with a 623-line shared support owner. The publication production module was 1784 lines and now has five concrete owners of 69-584 lines. CLI index and stress scenarios retain all 44 and 15 original normalized identities; the ledger retains all 74. The unchanged duplication thresholds now report zero clone pairs, versus eight initially. Advisory complexity reports no rank-D blocks or test function above cognitive complexity 20. Production complexity, nesting, lint, formatting, ty, strict basedpyright and pylint checks pass. The final health report analyzes 785 files with zero strict errors or warnings; the largest module is 1499 lines. No check threshold changed.

### live-validation | low | Real GPU and service coverage passes

The initial integration invocation stopped before tests because the resident service was 0.4.35 while the checkout is 0.5.2. After confirming no active jobs, the supervisor stopped it through the canonical CLI and started the compatible checkout interpreter on its existing port. The acknowledged borrower protocol remained enabled. Separate resident and subprocess-GPU selections passed 55 integration/performance cases and three diagnostics cases. They cover live watcher lifecycle and recovery, indexing/search headroom, codebase search, admission/preflight failures, Qdrant server mode and orphan lifecycle. A mixed-tier selection was correctly refused and rerun as separate selections. No GPU-tier prerequisite was bypassed.

### full-unit-validation | low | PASS across the settled unit tier

`just test-fast` exited zero: 5190 passed, five skipped, 779 deselected, 16 warnings in 949.97 seconds. The five pre-existing host-dependent skips cover four POSIX-only cases and the Windows access-denied PID branch, which is not reachable on this host. No skips were added by this change. The earlier temporary helper-renaming failure is resolved in the complete settled rerun, including torch-marked encode-bucket cases.

## Recommendations

PASS. The independent review and all planned covering and integrated checks pass. The approved cleanup is complete. Preserve the current scanner thresholds, canonical ownership and original test scenarios in future changes.
