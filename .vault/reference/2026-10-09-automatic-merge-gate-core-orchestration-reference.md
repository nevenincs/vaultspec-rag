---
tags:
  - '#reference'
  - '#automatic-merge-gate'
date: '2026-10-09'
modified: '2026-10-09'
body_schema: 'body-v2'
body_hash: 'sha256:880983d51b88d75bd11885a38ee264fc0d6eacdc8ff1ec1fd928d2c43f874899'
related: []
---

# `automatic-merge-gate` reference: `Core release orchestration`

## Summary

Core at commit `2e8e4aa0a729115dda250762359963c106de6870` starts its release orchestration on pushes to main. Candidate selection distinguishes an untagged merged proposal from ordinary feature work; only the former starts the exact-commit full gate and cut. Proposal refresh dispatches a full gate after its final lockfile write. Its result job fails when the selected path did not actually succeed. Locators: `Y:/code/vaultspec-core-worktrees/main/.github/workflows/release-please.yml:26`, `:124`, `:199`, `:393`.

Core releases held bot merge-gate runs after the full dispatched gate proves the current proposal SHA. The held PR verdict reuses proof on the same commit rather than mistaking skipped measuring jobs for passing tests. Locator: `Y:/code/vaultspec-core-worktrees/main/.github/workflows/merge-gate.yml:365`.

Core isolates the attestation grant in a job with no checkout or repository write. It signs only immutable artifacts after native offline proof, and release attachment depends on successful attestation. SHA256SUMS remains a consistency manifest rather than independent authority. Locator: `Y:/code/vaultspec-core-worktrees/main/.github/workflows/binaries.yml:823`.

RAG PR #596 at head `792d6694fde8a9787c16bb684d3c66f9e9a578c3` had a successful light dispatch and a later PR run with all measuring jobs skipped. The aggregate accepted the light success. The live protect-main ruleset requires the aggregate but has an administrator bypass. RAG also generated private pin proposals and required a separate reviewed catalog commit and verifier rerun, preventing unattended publication. Locators: `.github/workflows/release-please.yml:128`, `.github/workflows/merge-gate.yml:551`, `.github/workflows/binaries.yml:450`, `tools/monitor/pins.py:120`, `RELEASING.md:338`.

RAG must retain CUDA/MPS proof, four-target native proof, one wheel build, draft-first publication, and separate PyPI and channel credentials. Core's full-dispatch, exact-head readiness, push candidate selection and isolated provenance job fit those constraints. The canonical generated Dev server workflow can be dispatched on the proposal branch without editing its shared template. Its actual exact-SHA verdict must participate in release readiness.
