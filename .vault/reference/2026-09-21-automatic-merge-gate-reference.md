---
tags:
  - '#reference'
  - '#automatic-merge-gate'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:242a9dfa6ffa90335487a967deb845ae1660ab1950ae7290fa7a42636189ee68'
related: []
---

# `automatic-merge-gate` reference: `vaultspec-core automatic merge and release gates`

The reference implementation is `nevenincs/vaultspec-core` at commit
`066eee7670c5de301b147825645bc3d60fff91f7`. Its live repository ruleset and
recent workflow runs were also inspected on 2026-09-21.

## Summary

### One automatic pull-request lane owns the required verdict

Core's merge-gate workflow is the pull request's CI entry point. It listens to
`opened`, `reopened`, `synchronize`, `ready_for_review`, and `labeled`, so every
new ready pull-request head is measured without operator bookkeeping:
`Y:/code/vaultspec-core-worktrees/main/.github/workflows/merge-gate.yml:37`.

Draft state chooses cost. Draft pull requests run lint; ready pull requests run
lint plus Linux and Windows suites. The optional `ci:full` label only requests
a full proof while a pull request remains draft. It is not part of the normal
merge path: `Y:/code/vaultspec-core-worktrees/main/.github/workflows/merge-gate.yml:64`.

One aggregate job named `Check: Merge gate (Linux)` waits for every measuring
job and reports the exact context required by the live main-branch ruleset:
`Y:/code/vaultspec-core-worktrees/main/.github/workflows/merge-gate.yml:254`.
The ruleset requires strict up-to-date status and that single GitHub Actions
context. It has no merge-queue rule.

### Release automation dispatches the same gate

Changes made with the repository's default token do not start another Actions
workflow. Core therefore grants its release-please job `actions: write` and,
after all release-branch mutations, explicitly dispatches `merge-gate.yml`
against the release branch: `Y:/code/vaultspec-core-worktrees/main/.github/workflows/release-please.yml:1`
and `Y:/code/vaultspec-core-worktrees/main/.github/workflows/release-please.yml:143`.
The reusable gate accepts an optional ref and checks that ref out in every
measuring job: `Y:/code/vaultspec-core-worktrees/main/.github/workflows/merge-gate.yml:40`.

The dispatch run attaches its successful required check to the release branch
head even though GitHub separately records the suppressed pull-request run as
`action_required`. Core release PR 536 merged after this dispatched check
passed; the later release PR 542 reproduced the same successful dispatch on
its current head.

### Mapping to vaultspec-rag

RAG already has the same single required context and comparable lint, Linux,
Windows, and dependency-audit jobs. The transferable boundary is the trigger
and orchestration model: make the merge gate own automatic PR events, choose
full execution from ready state, accept a dispatch ref, and have
release-please dispatch it after refreshing the lock. RAG's accelerator jobs
remain outside the merge gate because they use separate power and GPU
availability contracts.
