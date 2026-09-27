---
tags:
  - '#plan'
  - '#open-issues-closeout'
date: '2026-09-27'
tier: L1
related:
  - '[[2026-09-21-typesafe-classifier-adr]]'
  - '[[2026-09-11-binary-release-bundles-adr]]'
  - '[[2026-09-23-status-messages-adr]]'
modified: '2026-09-27'
body_schema: body-v2
body_hash: 'sha256:82870b241fa1af42925d8b2ff9dcb680ce62f5e53ce172f8dc298bc5580db661'
---

# `open-issues-closeout` plan

## Description

Approved 2026-09-27

The user authorized all three open GitHub issues in one PR and exactly one complete local live campaign after implementation, with timing evidence audited after green. Earlier merged PR #548 already contains the primary fixes. This follow-up covers the remaining checksum uniqueness gap, model-facing punctuation normalization, and executable documentation regression coverage. Existing accepted hosted-classification, binary-release and operator-vocabulary decisions govern; no new protocol, persisted schema, or dependency is introduced.

## Steps

- [x] `S01` - Sanitize model-facing text and cover content-rejection recovery; `src/vaultspec_rag/search/_typesafe_transport.py, src/vaultspec_rag/tests/test_typesafe_transport.py`.
- [ ] `S02` - Require exact package checksum coverage and validate troubleshooting commands; `.github/workflows/publish.yml, tools/binaries/tests/test_release_workflow.py, src/vaultspec_rag/tests/integration/test_service_jobs_cli_basics.py`.
- [ ] `S03` - Run one local campaign, audit timing evidence, and prepare one pull request; `dev/, .vault/audit/, .vault/exec/`.

## Parallelization

Execute serially in this worktree. Finish both implementation Steps before the single live campaign; offline guard mutation checks may run first. Commit completed Steps after their covering checks pass. Create exactly one PR and do not merge it.

## Verification

Run explicit Python lint, format, type and workflow checks. Prove changed guards fail on their named mutations and pass after restoration. Run one local campaign from the settled tree, preserving commands, source digest, environment facts, exit codes, wall times, per-test phase durations and outcome counts. Audit slow tests and all skips or failures after the green signal before reporting completion. Historical PyPI/GitHub repair requires a reviewed release operation; do not bypass the archive and acquisition gates.
