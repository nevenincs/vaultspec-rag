---
tags:
  - '#plan'
  - '#code-health-cleanup'
date: '2026-09-27'
tier: L1
related:
  - '[[2026-06-01-module-split-adr]]'
  - '[[2026-07-27-maintainability-remediation-adr]]'
  - '[[2026-09-08-incremental-publication-cost-adr]]'
modified: '2026-09-27'
body_schema: body-v2
body_hash: 'sha256:4292c48403528c71948ef9ee5fc5c78beafe24f9136532f58cd45c992368aa01'
---

<!-- RETIRED: S02, S03, S04 -->

# `code-health-cleanup` plan

## Description

Approved 2026-09-27

The user authorized fixing all reported code-health findings, specifically the nearly four-thousand-line ledger test module. Reuse accepted direct-owner module decomposition and maintainability constraints; no new protocol, schema, dependency, or costly decision is introduced. Semantic discovery was attempted for this worktree but its missing index is non-authoritative; CLI decision listing and direct source reading supply grounding. Existing module-split and maintainability decisions govern all Steps; incremental-publication-cost governs preservation of ledger publication invariants in S01. Preserve all collected test scenarios, real integration behavior and current thresholds. Split all modules above 1500 physical lines; remove the eight detected clone pairs; simplify the rank-D test and the reported production complexity hotspots rather than suppress metrics. Existing unrelated open-issues-closeout edits remain owned by their session and must be preserved.

## Steps

- [x] `S01` - Resolve reported duplication, overlength modules and complexity hotspots while preserving behavior and test coverage; `src/vaultspec_rag production owners, split ledger and CLI/stress tests, shared test helpers, direct importers and ownership/substitution guards`.
- [ ] `S05` - Verify integrated health results and review direct ownership and preserved behavior; `src/vaultspec_rag, .vault/audit`.

## Parallelization

Within S01, ledger test decomposition, ledger production decomposition, and clone removal plus diagnostics simplification use disjoint worker ownership; the supervisor owns remaining splits and production simplification. Former S02-S04 are combined with S01 for one atomic implementation commit because the production/test import migrations, newly split CLI summary clone removal, and shared substitution registry couple the moves. Those identifiers are retired without changing authorized scope or dropping work. The supervisor preserves active session changes, serializes vault metadata and commits only the verified integrated implementation. Workers read whole owning modules and migrate direct imports. S05 integrated review follows implementation.

## Verification

Retain every pre-refactor test scenario and compare collected test identities across splits. Run covering pytest tests, Ruff lint and formatting, ty and strict basedpyright. Explicitly rerun duplication, production complexity, nesting, advisory complexity, health report and pylint length/class-shape gate. Require no remaining clone pairs at the unchanged scanner thresholds, no rank-D block, and no module above 1500 physical lines. Review integrated importer migration and publication invariants; do not introduce shims, exports, suppressions, skipped tests or relaxed thresholds.
