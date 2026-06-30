---
tags:
  - '#adr'
  - '#cli-tree-overhaul'
date: '2026-06-06'
modified: '2026-06-30'
related:
  - '[[2026-06-06-cli-tree-overhaul-research]]'
---

# `cli-tree-overhaul` adr: `CLI Tree Overhaul` | (**status:** `accepted`)

## Problem Statement

This ADR was reconstructed retrospectively after implementation: the work shipped under issue #169 (closed 2026-06-09) and the companion plan `2026-06-06-cli-tree-overhaul-plan`; the body was left empty at ship time and is being backfilled from those artefacts.

The operator-facing CLI presented a redundant double-nesting under `vaultspec-rag server service`: reaching daemon lifecycle required `server service start`, `server service stop`, `server service status`; reaching projects or watcher state required `server service projects list` and `server service watcher status`. The extra `service` layer added keystrokes and introduced terminology confusion — `server` and `service` both sound like natural entry-points for the same group of commands. Beyond the UX issue, the development harness (justfile) used `bash` as its shell on a Windows-first environment and lacked strict pipelines, and the Ruff configuration did not enforce tidy-imports discipline or cognitive-complexity gating — gaps that left code-health signals invisible during CI.

## Considerations

Three shapes were evaluated for the CLI collapse: (a) remove the `service` sub-app and hoist its commands directly under `server`, (b) keep the existing nesting but alias the redundant `server service` prefix, and (c) hoist `mcp` to the top level alongside `server`. Option (a) was chosen because it eliminates the confusion at the source and preserves `server` as the single natural namespace for all daemon-adjacent operations; aliasing (b) would have left the confusing structure in place; top-level `mcp` (c) was not pursued because the MCP adapter is a server-management concern, not a peer to the server itself.

For the harness, converting the justfile to PowerShell with strict-mode pipelines was weighed against cross-platform shell scripts. PowerShell was selected to match the Windows-first development environment and to gain native strict-pipeline semantics. For code-quality gating, `xenon` and `flake8-cognitive-complexity` were added alongside Ruff's built-in `mccabe` and `TID` (tidy-imports) rules to enforce import discipline and flag complex functions at CI time.

## Constraints

The justfile shell must be PowerShell (`pwsh`) because the primary development machine is Windows; Bash-only targets would silently fail or require WSL context-switching. The CLI restructure must keep `server` as the top-level entry point so that operators already familiar with `vaultspec-rag server` do not need to relearn the root; only the `service` indirection is removed. Removing test skips and `noqa` annotations unshields failures that were previously hidden — the plan explicitly required remediating all newly-surfaced failures within the same effort rather than deferring them, to avoid leaving the codebase in a partially-shielded state.

## Implementation

The work executed in three waves. **W01 (Core Overhaul, P01)** converted the justfile to use `set shell := ["pwsh", ...]` with `$ErrorActionPreference = 'Stop'` pipelines and rewrote all targets (`default`, `prod`, `dev-deps`, `dev-lint`, `dev-fix`, `dev-audit`, `dev-test`, `dev-build`, `dev-precommit`, `ci`) accordingly. The `server service` sub-app was collapsed: all lifecycle commands (`start`, `stop`, `status`, `warmup`, `logs`, `jobs`, `info`) moved directly under `server`; `server projects` (`list`, `evict`) and `server watcher` (`status`, `start`, `stop`, `reconfigure`) became direct sub-apps; `server mcp` (`start`, `stop`, `status`) was retained for the stdio adapter. **W02 (Code Quality Rules, P02)** added `xenon` and `flake8-cognitive-complexity` as dev dependencies, configured Ruff to enforce `TID` and `C901`/mccabe complexity rules, and added a `dev-complexity-check` justfile target wired into CI. **W03 (Remediation, P03)** removed test skips and `noqa` annotations and fixed the exposed failures: unused-argument (`ARG`) lint violations in tests, 23 failing integration tests, 14 Pyright type errors introduced during cognitive-complexity refactoring, missing `step_id` frontmatter in exec records, and 10 test regressions from the type-safety pass. The resulting `server` tree is visible today via `vaultspec-rag server --help`: `info, jobs, start, stop, status, warmup, logs, mcp, projects, watcher`.

## Rationale

Collapsing `service` into `server` directly addresses discoverability: operators reach `server` instinctively for daemon control, and the extra `service` layer provided no organisational benefit — both words described the same concept. The change reduces every daemon-lifecycle command by one segment. Adopting pwsh strict pipelines closes a long-standing gap where CI could succeed despite silent pipeline failures on Windows. Complexity and tidy-imports gates produce a durable, machine-readable code-health signal that survives contributor turnover; calibrating them against a baseline and integrating into CI ensures the signal tightens over time rather than decaying. Remediating unshielded failures in-place rather than deferring was necessary to avoid a split state where removing skips was blocked on a follow-up issue that might never be prioritised.

## Consequences

**Positive:** The `server` command tree is flatter and easier to navigate. Strict pwsh pipelines catch Windows-specific CI failures that were previously invisible. Ruff TID + C901 + cognitive-complexity gates are enforced on every PR. The unshielded codebase — previously hidden behind skips and `noqa` annotations — is now tested cleanly with 727 unit tests passing. **Cost/debt:** The justfile is now pwsh-coupled; contributors on Linux or macOS must use `pwsh` (available but not the default shell). The complexity gates are calibrated to the baseline present at ship time; they will not automatically tighten as the codebase grows — a future ratchet pass is needed to lower the thresholds incrementally. The research document and this ADR were left with empty bodies when the feature was marked complete, requiring a retrospective backfill — a documentation-discipline gap that cost time.

## Codification candidates

- **ADR and research bodies must be authored before a feature is marked complete, not after.** Leaving these empty at ship time requires a retrospective reconstruction pass and breaks the documentation dependency chain.
- **Dev-harness complexity gates ship baseline-calibrated with a documented ratchet path.** Gates set once and never lowered decay into noise; the ratchet path (periodic threshold reductions) must be documented at the time the gates are introduced.
